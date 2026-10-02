import { createHash } from "node:crypto";
import type { IncomingMessage } from "node:http";

import { describe, expect, it, vi } from "vitest";

import {
  makeApiGet,
  parseBearer,
  TokenAuthCache,
  tokenHash,
  wrapToolHandler,
  type AccessLogEntry,
} from "@/mcp/server";
import type { McpTool, ToolCtx } from "@/mcp/types";

const ctx: ToolCtx = {
  db: {} as ToolCtx["db"],
  apiGet: async () => ({}),
  tokenLabel: "grok",
};

function reqWithAuth(header?: string): IncomingMessage {
  return { headers: header ? { authorization: header } : {} } as IncomingMessage;
}

describe("parseBearer", () => {
  it("extracts the token from a Bearer header", () => {
    expect(parseBearer(reqWithAuth("Bearer abc.def"))).toBe("abc.def");
    expect(parseBearer(reqWithAuth("bearer abc"))).toBe("abc");
  });
  it("rejects missing, wrong-scheme and empty tokens", () => {
    expect(parseBearer(reqWithAuth())).toBeNull();
    expect(parseBearer(reqWithAuth("Basic abc"))).toBeNull();
    expect(parseBearer(reqWithAuth("Bearer "))).toBeNull();
    expect(parseBearer(reqWithAuth("Bearer"))).toBeNull();
  });
});

describe("tokenHash", () => {
  it("is the sha256 hex the DB stores", () => {
    expect(tokenHash("tok")).toBe(createHash("sha256").update("tok").digest("hex"));
    expect(tokenHash("tok")).toHaveLength(64);
  });
});

describe("TokenAuthCache", () => {
  it("resolves the label once and serves the second call from cache", async () => {
    const lookup = vi.fn().mockResolvedValue("grok");
    const auth = new TokenAuthCache(lookup);
    expect(await auth.labelForToken("t1")).toBe("grok");
    expect(await auth.labelForToken("t1")).toBe("grok");
    expect(lookup).toHaveBeenCalledTimes(1);
    expect(lookup).toHaveBeenCalledWith(tokenHash("t1"));
  });
  it("re-queries after the 60 s ttl", async () => {
    const lookup = vi.fn().mockResolvedValue("grok");
    let now = 1_000;
    const auth = new TokenAuthCache(lookup, 60_000, () => now);
    await auth.labelForToken("t1");
    now += 59_999;
    await auth.labelForToken("t1");
    expect(lookup).toHaveBeenCalledTimes(1);
    now += 2;
    await auth.labelForToken("t1");
    expect(lookup).toHaveBeenCalledTimes(2);
  });
  it("returns null for unknown/revoked tokens and never caches them", async () => {
    const lookup = vi.fn().mockResolvedValue(null);
    const auth = new TokenAuthCache(lookup);
    expect(await auth.labelForToken("bad")).toBeNull();
    expect(await auth.labelForToken("bad")).toBeNull();
    expect(lookup).toHaveBeenCalledTimes(2);
  });
});

describe("wrapToolHandler access log", () => {
  const tool: McpTool = {
    name: "read",
    description: "t",
    inputSchema: {},
    handler: async (args) => ({ echo: args }),
  };

  function makeSink() {
    const rows: AccessLogEntry[] = [];
    return { rows, sink: vi.fn(async (e: AccessLogEntry) => void rows.push(e)) };
  }

  it("logs one ok row with args, bytes and duration on success", async () => {
    const { rows, sink } = makeSink();
    const result = await wrapToolHandler(tool, ctx, sink)({ path: "/health" });
    expect(result.content).toEqual([{ type: "text", text: '{"echo":{"path":"/health"}}' }]);
    expect(result.structuredContent).toEqual({ echo: { path: "/health" } });
    expect(rows).toHaveLength(1);
    const row = rows[0];
    expect(row).toMatchObject({
      tokenLabel: "grok",
      tool: "read",
      args: { path: "/health" },
      status: "ok",
      responseBytes: Buffer.byteLength('{"echo":{"path":"/health"}}'),
    });
    expect(row.durationMs).toBeGreaterThanOrEqual(0);
  });

  it("logs status=error and rethrows when the handler fails", async () => {
    const { rows, sink } = makeSink();
    const bad: McpTool = {
      ...tool,
      handler: async () => {
        throw new Error("boom");
      },
    };
    await expect(wrapToolHandler(bad, ctx, sink)({})).rejects.toThrow("boom");
    expect(rows).toHaveLength(1);
    expect(rows[0]).toMatchObject({ status: "error", tool: "read", responseBytes: 0 });
  });

  it("omits structuredContent for non-object payloads", async () => {
    const { sink } = makeSink();
    const scalar: McpTool = { ...tool, handler: async () => [1, 2] };
    const result = await wrapToolHandler(scalar, ctx, sink)({});
    expect(result.structuredContent).toBeUndefined();
    expect(result.content[0]).toEqual({ type: "text", text: "[1,2]" });
  });

  it("still returns the result when the log write fails", async () => {
    const spy = vi.spyOn(console, "error").mockImplementation(() => {});
    const failing = async () => {
      throw new Error("db down");
    };
    const result = await wrapToolHandler(tool, ctx, failing)({});
    expect(result.structuredContent).toEqual({ echo: {} });
    spy.mockRestore();
  });
});

describe("makeApiGet", () => {
  it("issues a GET to {base}/api{path} with stringified params", async () => {
    const spy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ n: 1 }) });
    vi.stubGlobal("fetch", spy);
    const get = makeApiGet("http://api:8400");
    await expect(get("/health", { a: 1, b: "x y" })).resolves.toEqual({ n: 1 });
    expect(spy).toHaveBeenCalledWith("http://api:8400/api/health?a=1&b=x+y", { method: "GET" });
    vi.unstubAllGlobals();
  });

  it("throws on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(makeApiGet("http://api:8400")("/x")).rejects.toThrow("503");
    vi.unstubAllGlobals();
  });
});
