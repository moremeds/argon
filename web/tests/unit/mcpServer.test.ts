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
  function fakeSession(lastSeen: number, sseStreams = 0) {
    return {
      transport: { close: vi.fn(async () => {}), sessionId: "x" },
      lastSeen,
      sseStreams,
    } as unknown as Session;
  }

  it("closes + drops sessions idle past the limit, keeps live ones", () => {
    const now = 1_000_000;
    const store = new SessionStore(() => now, 30 * 60_000);
    const old = fakeSession(now - 31 * 60_000);
    const fresh = fakeSession(now - 60_000);
    const streaming = fakeSession(now - 40 * 60_000, /* sseStreams */ 1);
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
  afterEach(() => vi.unstubAllGlobals());

  it("issues a GET to {base}/api{path} with stringified params", async () => {
    const spy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({ n: 1 }) });
    vi.stubGlobal("fetch", spy);
    const get = makeApiGet("http://api:8400");
    await expect(get("/health", { a: 1, b: "x y" })).resolves.toEqual({ n: 1 });
    const [url, init] = spy.mock.calls[0];
    expect(url).toBeInstanceOf(URL);
    expect(url.href).toBe("http://api:8400/api/health?a=1&b=x+y");
    expect(init.method).toBe("GET");
    expect(init.signal).toBeInstanceOf(AbortSignal); // 30s timeout, not hung-forever
  });

  it("throws on a non-2xx response", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue({ ok: false, status: 503 }));
    await expect(makeApiGet("http://api:8400")("/x")).rejects.toThrow("503");
  });

  it("refuses paths whose URL-normalized pathname differs from the request", async () => {
    const spy = vi.fn().mockResolvedValue({ ok: true, json: async () => ({}) });
    vi.stubGlobal("fetch", spy);
    const get = makeApiGet("http://api:8400");
    // WHATWG resolves dot segments/backslashes and truncates at '?'/'#' — the
    // parsed pathname no longer equals what was asked for → hard reject.
    for (const p of ["/stock/../x", "/stock/..\\x", "/a?b", "/a#b", "/%2e%2e/x"]) {
      await expect(get(p)).rejects.toThrow(/normalization mismatch/);
    }
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("SSE event stream", () => {
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
  const headers = (sid?: string) => ({
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: "Bearer good-token",
    ...(sid ? { "mcp-session-id": sid } : {}),
  });

  it("re-checks revocation before each event; revoked → unsubscribed + session deleted", async () => {
    let labelActive = true;
    // pool.query serves both the access log and the per-event revocation check.
    const poolQuery = vi.fn(async (text: string) =>
      text.startsWith("SELECT 1") ? { rows: labelActive ? [{ "?column?": 1 }] : [] } : { rows: [] },
    );
    let sendEvent: ((e: unknown) => void) | undefined;
    const unsub = vi.fn();
    const hook = vi.fn(async (_c: ToolCtx, send: (e: unknown) => void) => {
      sendEvent = send;
      return unsub;
    });
    const handler = makeRequestHandler(
      {
        pool: { query: poolQuery } as never,
        labelForToken: async (t) => (t === "good-token" ? "grok" : null),
        apiGet: async () => ({}),
      },
      { subscribeEvents: hook },
    );
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

    const init = await fetch(`${base}/mcp`, { method: "POST", headers: headers(), body: initBody });
    const sid = init.headers.get("mcp-session-id")!;
    const sse = await fetch(`${base}/mcp`, { headers: headers(sid) });
    expect(sse.status).toBe(200);
    await vi.waitFor(() => expect(sendEvent).toBeDefined());

    // Token active → the event reaches the stream as an argon_event frame.
    const reader = sse.body!.getReader();
    sendEvent!({ id: 1 });
    const chunk = await reader.read();
    expect(new TextDecoder().decode(chunk.value)).toContain("argon_event");

    // Revoked → the next event is dropped, the subscriber unsubscribed and
    // the session deleted (a follow-up call on it gets 404, not data).
    labelActive = false;
    sendEvent!({ id: 2 });
    await vi.waitFor(() => expect(unsub).toHaveBeenCalled());
    await vi.waitFor(async () => {
      const call = await fetch(`${base}/mcp`, {
        method: "POST",
        headers: headers(sid),
        body: JSON.stringify({ jsonrpc: "2.0", id: 3, method: "tools/list" }),
      });
      expect(call.status).toBe(404);
    });
  });

  it("unsubscribes when the client disconnects while subscribeEvents is pending", async () => {
    let resolveSub!: (fn: () => void) => void;
    const gate = new Promise<() => void>((r) => (resolveSub = r));
    const unsub = vi.fn();
    const hook = vi.fn(async () => {
      await gate;
      return unsub;
    });
    const handler = makeRequestHandler(
      {
        pool: { query: vi.fn(async () => ({ rows: [{}] })) } as never,
        labelForToken: async () => "grok",
        apiGet: async () => ({}),
      },
      { subscribeEvents: hook },
    );
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

    const init = await fetch(`${base}/mcp`, { method: "POST", headers: headers(), body: initBody });
    const sid = init.headers.get("mcp-session-id")!;

    const ac = new AbortController();
    const sse = fetch(`${base}/mcp`, { headers: headers(sid), signal: ac.signal }).catch(() => null);
    await vi.waitFor(() => expect(hook).toHaveBeenCalled());
    ac.abort(); // client gone before subscribeEvents resolved
    await new Promise((r) => setTimeout(r, 50)); // let res 'close' fire
    resolveSub(unsub);
    await vi.waitFor(() => expect(unsub).toHaveBeenCalledTimes(1));
    await sse;
  });

  it("answers 503 instead of opening the stream when subscribeEvents throws", async () => {
    const hook = vi.fn(async () => {
      throw new Error("pg down");
    });
    const handler = makeRequestHandler(
      {
        pool: { query: vi.fn(async () => ({ rows: [{}] })) } as never,
        labelForToken: async () => "grok",
        apiGet: async () => ({}),
      },
      { subscribeEvents: hook },
    );
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

    const init = await fetch(`${base}/mcp`, { method: "POST", headers: headers(), body: initBody });
    const sid = init.headers.get("mcp-session-id")!;
    const sse = await fetch(`${base}/mcp`, { headers: headers(sid) });
    expect(sse.status).toBe(503);
  });

  it("a second GET gets 409 without touching stream 1's subscription", async () => {
    const unsubs: ReturnType<typeof vi.fn>[] = [];
    const hook = vi.fn(async () => {
      const u = vi.fn();
      unsubs.push(u);
      return u;
    });
    const handler = makeRequestHandler(
      {
        pool: { query: vi.fn(async () => ({ rows: [{}] })) } as never,
        labelForToken: async () => "grok",
        apiGet: async () => ({}),
      },
      { subscribeEvents: hook },
    );
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

    const init = await fetch(`${base}/mcp`, { method: "POST", headers: headers(), body: initBody });
    const sid = init.headers.get("mcp-session-id")!;

    const sse1 = await fetch(`${base}/mcp`, { headers: headers(sid) });
    expect(sse1.status).toBe(200);
    await vi.waitFor(() => expect(unsubs).toHaveLength(1));
    // Second standalone GET — we answer 409 ourselves BEFORE subscribing, so
    // stream 1's subscription is untouched.
    const sse2 = await fetch(`${base}/mcp`, { headers: headers(sid) });
    expect(sse2.status).toBe(409);
    expect(unsubs).toHaveLength(1);
    expect(unsubs[0]).not.toHaveBeenCalled();
    await sse1.body?.cancel(); // now stream 1 goes away → its own unsub
    await vi.waitFor(() => expect(unsubs[0]).toHaveBeenCalled());
  });

  it("a live SSE stream exempts its session from sweep; closing makes it sweepable", async () => {
    let now = 1_000_000;
    const store = new SessionStore(() => now, 30 * 60_000);
    // The REAL transport.handleRequest stays pending for the stream's whole
    // life (Hono awaits the body write) — this exercises the true timing,
    // not a mocked resolve.
    const handler = makeRequestHandler(
      {
        pool: { query: vi.fn(async () => ({ rows: [{}] })) } as never,
        labelForToken: async () => "grok",
        apiGet: async () => ({}),
      },
      {
        now: () => now,
        sessions: store,
        subscribeEvents: vi.fn(async () => vi.fn()),
      },
    );
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;

    const init = await fetch(`${base}/mcp`, { method: "POST", headers: headers(), body: initBody });
    const sid = init.headers.get("mcp-session-id")!;
    const sse = await fetch(`${base}/mcp`, { headers: headers(sid) });
    expect(sse.status).toBe(200);
    // The exemption is set while the (real) handleRequest is still pending.
    await vi.waitFor(() => expect(store.get(sid)?.sseStreams).toBe(1));

    now += 31 * 60_000; // idle past the limit — but the stream is live
    store.sweep();
    expect(store.get(sid)).toBeDefined();

    await sse.body?.cancel(); // closing the client socket ends the stream
    await vi.waitFor(() => expect(store.get(sid)?.sseStreams).toBe(0));

    now += 31 * 60_000;
    store.sweep();
    expect(store.get(sid)).toBeUndefined();
  });
});

describe("SDK-rejected tool calls still write one access-log row", () => {
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
  const headers = (sid?: string) => ({
    "content-type": "application/json",
    accept: "application/json, text/event-stream",
    authorization: "Bearer good-token",
    ...(sid ? { "mcp-session-id": sid } : {}),
  });

  it("unknown tool + schema-invalid + handler-fail each log exactly one error row", async () => {
    const inserts: unknown[][] = [];
    const poolQuery = vi.fn(async (text: string, params?: unknown[]) => {
      if (text.includes("mcp_access_log")) inserts.push(params ?? []);
      return { rows: [] };
    });
    const handler = makeRequestHandler({
      pool: { query: poolQuery } as never,
      labelForToken: async () => "grok",
      apiGet: async () => ({}),
    });
    server = createServer(handler);
    await new Promise<void>((r) => server!.listen(0, r));
    const base = `http://127.0.0.1:${(server.address() as AddressInfo).port}`;
    const init = await fetch(`${base}/mcp`, { method: "POST", headers: headers(), body: initBody });
    const sid = init.headers.get("mcp-session-id")!;

    const call = async (id: number, name: string, args: unknown) => {
      const res = await fetch(`${base}/mcp`, {
        method: "POST",
        headers: headers(sid),
        body: JSON.stringify({
          jsonrpc: "2.0",
          id,
          method: "tools/call",
          params: { name, arguments: args },
        }),
      });
      const text = await res.text();
      // Session-scoped replies are SSE-framed: "event: message\ndata: {...}"
      const data = text.split("\n").find((l) => l.startsWith("data:"));
      return JSON.parse(data!.slice(5)) as { result?: { isError?: boolean } };
    };

    // Unknown tool → SDK InvalidParams → isError, no handler ran → 1 row.
    const r1 = await call(2, "nope_tool", {});
    expect(r1.result?.isError).toBe(true);
    // Schema-invalid → validation error before the handler → 1 row.
    const r2 = await call(3, "read", {});
    expect(r2.result?.isError).toBe(true);
    // Handler reached and failed (openapi fetch unavailable) → wrapToolHandler
    // logs once; the ACCESS_LOGGED marker must stop the outer wrapper's row.
    const r3 = await call(4, "read", { path: "/x" });
    expect(r3.result?.isError).toBe(true);

    const byTool = (n: string) => inserts.filter((p) => p[1] === n);
    expect(byTool("nope_tool")).toHaveLength(1);
    expect(byTool("read")).toHaveLength(2); // schema-invalid + handler-fail
    for (const row of inserts) expect(row[3]).toBe("error");
  });
});
