import { createHash } from "node:crypto";
import { createServer, type IncomingMessage } from "node:http";
import type { AddressInfo } from "node:net";

import { afterEach, describe, expect, it, vi } from "vitest";

import {
  makeApiGet,
  makeLabelForToken,
  makeRequestHandler,
  parseBearer,
  SessionStore,
  tokenHash,
  wrapToolHandler,
  type AccessLogEntry,
  type Session,
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

describe("makeLabelForToken", () => {
  it("queries sha256 vs mcp_token and returns the label or null", async () => {
    const query = vi
      .fn()
      .mockResolvedValueOnce({ rows: [{ label: "grok" }] })
      .mockResolvedValueOnce({ rows: [] });
    const labelFor = makeLabelForToken({ query } as never);
    await expect(labelFor("good")).resolves.toBe("grok");
    expect(query).toHaveBeenCalledWith(expect.stringContaining("revoked_at IS NULL"), [
      tokenHash("good"),
    ]);
    await expect(labelFor("bad")).resolves.toBeNull();
  });
});

describe("revocation is immediate (no auth cache)", () => {
  let server: ReturnType<typeof createServer> | undefined;
  afterEach(async () => {
    await new Promise((r) => server?.close(r));
    server = undefined;
  });

  const initBody = JSON.stringify({
    jsonrpc: "2.0",
    id: 1,
    method: "initialize",
    params: {
      protocolVersion: "2025-03-26",
      capabilities: {},
      clientInfo: { name: "t", version: "0" },
    },
  });
  const mcpHeaders = (token: string, sid?: string) => ({
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: `Bearer ${token}`,
    ...(sid ? { "mcp-session-id": sid } : {}),
  });

  it("valid → revoked → next request 401s, even on a live session", async () => {
    const valid = new Set(["good-token"]);
    const handler = makeRequestHandler({
      pool: { query: vi.fn() } as never,
      labelForToken: async (t) => (valid.has(t) ? "grok" : null),
      apiGet: async () => ({}),
    });
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

    const init = await fetch(`${base}/mcp`, {
      method: "POST",
      headers: mcpHeaders("good-token"),
      body: initBody,
    });
    expect(init.status).toBe(200);
    const sid = init.headers.get("mcp-session-id")!;
    expect(sid).toBeTruthy();

    valid.delete("good-token"); // token revoked in mcp_token

    // The next request — on the still-open session — is rejected immediately.
    const call = await fetch(`${base}/mcp`, {
      method: "POST",
      headers: mcpHeaders("good-token", sid),
      body: JSON.stringify({ jsonrpc: "2.0", id: 2, method: "tools/list" }),
    });
    expect(call.status).toBe(401);
    // And a fresh initialize with the same token is rejected too.
    const reinit = await fetch(`${base}/mcp`, {
      method: "POST",
      headers: mcpHeaders("good-token"),
      body: initBody,
    });
    expect(reinit.status).toBe(401);
  });
});

describe("SessionStore.sweep", () => {
  function fakeSession(lastSeen: number, sseOpen = false) {
    return {
      transport: { close: vi.fn(async () => {}), sessionId: "x" },
      lastSeen,
      sseOpen,
    } as unknown as Session;
  }

  it("closes + drops sessions idle past the limit, keeps live ones", () => {
    let now = 1_000_000;
    const store = new SessionStore(() => now, 30 * 60_000);
    const old = fakeSession(now - 31 * 60_000);
    const fresh = fakeSession(now - 60_000);
    const streaming = fakeSession(now - 40 * 60_000, /* sseOpen */ true);
    store.set("old", old);
    store.set("fresh", fresh);
    store.set("streaming", streaming);

    store.sweep();

    expect(old.transport.close).toHaveBeenCalledOnce();
    expect(store.get("old")).toBeUndefined();
    expect(store.get("fresh")).toBe(fresh);
    expect(store.get("streaming")).toBe(streaming); // live SSE exempt
    expect(fresh.transport.close).not.toHaveBeenCalled();
    expect(store.size).toBe(2);
  });

  it("touch() keeps a session alive", () => {
    let now = 1_000_000;
    const store = new SessionStore(() => now, 30 * 60_000);
    const s = fakeSession(now - 29 * 60_000);
    store.set("s", s);
    now += 2 * 60_000; // would be 31 min idle without activity
    store.touch("s");
    store.sweep();
    expect(store.get("s")).toBe(s);
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
