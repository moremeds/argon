import { afterEach, describe, expect, it, vi } from "vitest";

import {
  endpointsCache,
  EndpointsCache,
  matchEndpoint,
  parseOpenApiEndpoints,
  type EndpointInfo,
} from "@/mcp/lib/endpoints";
import { tool as read } from "@/mcp/tools/read";
import { tool as listEndpoints } from "@/mcp/tools/list_endpoints";
import type { ToolCtx } from "@/mcp/types";

const doc = {
  paths: {
    "/api/health": { get: { summary: "Health check" } },
    "/api/stock/{ticker}/technicals": {
      get: {
        summary: "Technicals",
        parameters: [
          { name: "ticker", in: "path", required: true },
          { name: "window", in: "query", required: false },
        ],
      },
      post: { summary: "Mutate" }, // must not leak into the allowlist
    },
    "/api/watchlist": {
      get: { summary: "Watchlist" },
      delete: { summary: "Delete" },
    },
    "/api/no-get": { post: { summary: "POST only" } },
  },
};

const eps: EndpointInfo[] = [
  { path: "/health", summary: "Health check", params: [] },
  {
    path: "/stock/{ticker}/technicals",
    summary: "Technicals",
    params: [
      { name: "ticker", in: "path", required: true },
      { name: "window", in: "query", required: false },
    ],
  },
  { path: "/watchlist", summary: "Watchlist", params: [] },
];

const ctx: ToolCtx = {
  db: {} as ToolCtx["db"],
  apiGet: vi.fn(async () => ({ ok: true })),
  tokenLabel: "t",
};

afterEach(() => vi.restoreAllMocks());

describe("parseOpenApiEndpoints", () => {
  it("keeps GET ops only, strips /api, extracts params", () => {
    const parsed = parseOpenApiEndpoints(doc);
    expect(parsed.map((e) => e.path)).toEqual([
      "/health",
      "/stock/{ticker}/technicals",
      "/watchlist",
    ]);
    expect(parsed[1].params).toEqual([
      { name: "ticker", in: "path", required: true },
      { name: "window", in: "query", required: false },
    ]);
    expect(parsed.find((e) => e.path === "/no-get")).toBeUndefined();
  });

  it("throws on a doc without paths", () => {
    expect(() => parseOpenApiEndpoints({})).toThrow("paths");
  });
});

describe("matchEndpoint", () => {
  it("matches literal paths", () => {
    expect(matchEndpoint(eps, "/health")?.summary).toBe("Health check");
  });
  it("matches {param} templates segment-wise", () => {
    expect(matchEndpoint(eps, "/stock/AAPL/technicals")?.path).toBe(
      "/stock/{ticker}/technicals",
    );
  });
  it("rejects wrong segment counts, wrong literals and empty params", () => {
    expect(matchEndpoint(eps, "/stock/AAPL")).toBeNull();
    expect(matchEndpoint(eps, "/stock/AAPL/other")).toBeNull();
    expect(matchEndpoint(eps, "/stock//technicals")).toBeNull();
    expect(matchEndpoint(eps, "/nope")).toBeNull();
  });
});

describe("read tool", () => {
  it("calls apiGet for a concrete allowlisted path, passing query params", async () => {
    vi.spyOn(endpointsCache, "get").mockResolvedValue(eps);
    const apiGet = vi.fn(async () => ({ data: 1 }));
    const out = await read.handler(
      { path: "/stock/AAPL/technicals", params: { window: "1h" } },
      { ...ctx, apiGet },
    );
    expect(out).toEqual({ data: 1 });
    expect(apiGet).toHaveBeenCalledWith("/stock/AAPL/technicals", {
      window: "1h",
    });
  });

  it("fills {placeholder} segments from params and removes them from the query", async () => {
    vi.spyOn(endpointsCache, "get").mockResolvedValue(eps);
    const apiGet = vi.fn(async () => ({}));
    await read.handler(
      {
        path: "/stock/{ticker}/technicals",
        params: { ticker: "AAPL", window: 21 },
      },
      { ...ctx, apiGet },
    );
    expect(apiGet).toHaveBeenCalledWith("/stock/AAPL/technicals", {
      window: 21,
    });
  });

  it("rejects non-allowlisted paths and points at list_endpoints", async () => {
    vi.spyOn(endpointsCache, "get").mockResolvedValue(eps);
    await expect(read.handler({ path: "/admin" }, ctx)).rejects.toThrow(
      /not an allowlisted GET endpoint.*list_endpoints/,
    );
    await expect(read.handler({ path: "/no-get" }, ctx)).rejects.toThrow(
      /allowlisted/,
    );
  });

  it("rejects '..', '//' and unfilled placeholders before matching", async () => {
    const getSpy = vi.spyOn(endpointsCache, "get");
    await expect(read.handler({ path: "/../etc" }, ctx)).rejects.toThrow(
      /invalid path/,
    );
    await expect(read.handler({ path: "/a//b" }, ctx)).rejects.toThrow(
      /invalid path/,
    );
    await expect(
      read.handler({ path: "/stock/{ticker}/technicals" }, ctx),
    ).rejects.toThrow(/missing value.*ticker/);
    await expect(
      read.handler(
        {
          path: "/stock/{ticker}/technicals",
          params: { ticker: ".." },
        },
        ctx,
      ),
    ).rejects.toThrow(/invalid path/);
    expect(getSpy).not.toHaveBeenCalled();
  });
});

describe("list_endpoints tool", () => {
  it("returns [{path, summary, params}] from the cache", async () => {
    vi.spyOn(endpointsCache, "get").mockResolvedValue(eps);
    const out = await listEndpoints.handler({}, ctx);
    expect(out).toEqual(eps);
  });
});

describe("EndpointsCache", () => {
  const freshDoc = { paths: { "/api/x": { get: {} } } };

  it("fetches once, serves cache, refreshes after ttl, keeps stale on error", async () => {
    let now = 0;
    const fetchDoc = vi.fn(async () => freshDoc);
    const cache = new EndpointsCache(fetchDoc, () => now, 3600);
    expect(await cache.get()).toEqual([{ path: "/x", summary: "", params: [] }]);
    expect(await cache.get()).toHaveLength(1);
    expect(fetchDoc).toHaveBeenCalledTimes(1);

    now += 3601; // ttl expired → refetch
    await cache.get();
    expect(fetchDoc).toHaveBeenCalledTimes(2);

    now += 3601;
    fetchDoc.mockRejectedValueOnce(new Error("api down"));
    await expect(cache.get()).resolves.toHaveLength(1); // stale kept
  });

  it("propagates the error when there is no cached copy", async () => {
    const cache = new EndpointsCache(
      vi.fn(async () => {
        throw new Error("no doc");
      }),
      () => 0,
    );
    await expect(cache.get()).rejects.toThrow("no doc");
  });

  it("dedupes concurrent first fetches", async () => {
    let resolve: (v: unknown) => void;
    const gate = new Promise((r) => (resolve = r));
    const fetchDoc = vi.fn(() => gate.then(() => freshDoc));
    const cache = new EndpointsCache(fetchDoc, () => 0);
    const p1 = cache.get();
    const p2 = cache.get();
    resolve!(null);
    const [a, b] = await Promise.all([p1, p2]);
    expect(fetchDoc).toHaveBeenCalledTimes(1);
    expect(a).toBe(b);
  });
});
