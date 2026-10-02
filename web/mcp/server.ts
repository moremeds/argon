// web/mcp/server.ts — agent MCP server (streamable HTTP, stateful sessions).
// Spec: docs/superpowers/specs/2026-10-02-agent-mcp-design.md.
//
//   POST /mcp   JSON-RPC (initialize creates a session bound to the bearer label)
//   GET  /mcp   standalone SSE stream: subscribeEvents(ctx, send, close) + 30 s
//               keepalive comment; close() ends the stream via the transport
//   DELETE /mcp session teardown
//   GET  /healthz
//
// Auth: Authorization: Bearer <token> → sha256 hex → mcp_token lookup
// (revoked_at IS NULL), one lookup per request so revocation is immediate.
// Every tool call writes one mcp_access_log row. apiGet is the only HTTP call
// this module makes and it is GET-only — there is no other verb, so the
// read-only guarantee is auditable by reading this file.
// Sessions idle > SESSION_IDLE_MS with no live SSE stream are closed by an
// unref'd sweeper — cloud agents open a session per run and rarely DELETE.
import { createHash, randomUUID } from "node:crypto";
import { createServer, type IncomingMessage, type ServerResponse } from "node:http";
import { pathToFileURL } from "node:url";

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StreamableHTTPServerTransport } from "@modelcontextprotocol/sdk/server/streamableHttp.js";
import { isInitializeRequest, type CallToolResult } from "@modelcontextprotocol/sdk/types.js";
import pg from "pg";

import { subscribeEvents } from "./events";
import { TOOLS } from "./tools/index";
import type { McpTool, ToolCtx } from "./types";

const MCP_PATH = "/mcp";
const HEALTHZ_PATH = "/healthz";
const SESSION_IDLE_MS = 30 * 60_000;
const SESSION_SWEEP_MS = 60_000;
const SSE_KEEPALIVE_MS = 30_000; // Cloudflare drops idle tunnels at ~125 s
const MAX_BODY_BYTES = 1_048_576;
// JSON-RPC method pushed over the standalone SSE stream by send().
const SSE_EVENT_METHOD = "notifications/argon_event";

// ---------------------------------------------------------------------------
// bearer auth
// ---------------------------------------------------------------------------

/** Extract the bearer token, or null when the header is absent/malformed. */
export function parseBearer(req: IncomingMessage): string | null {
  const header = req.headers.authorization;
  if (!header) return null;
  const [scheme, token] = header.split(" ", 2);
  if (scheme?.toLowerCase() !== "bearer" || !token) return null;
  return token.trim() || null;
}

export function tokenHash(token: string): string {
  return createHash("sha256").update(token).digest("hex");
}

export type LabelForToken = (token: string) => Promise<string | null>;

/** sha256 → label for active tokens; null for unknown/revoked. Called once per
 *  request — revocation takes effect on the next request, not within a cache
 *  window. */
export function makeLabelForToken(pool: pg.Pool): LabelForToken {
  return async (token) => {
    const r = await pool.query<{ label: string }>(
      "SELECT label FROM uw_scan.mcp_token WHERE token_hash = $1 AND revoked_at IS NULL",
      [tokenHash(token)],
    );
    return r.rows[0]?.label ?? null;
  };
}

// ---------------------------------------------------------------------------
// ToolCtx — apiGet is the ONLY HTTP call in this module, and it is GET-only.
// ---------------------------------------------------------------------------

export function makeApiGet(apiBase: string): ToolCtx["apiGet"] {
  return async (path, params) => {
    const qs = params
      ? "?" + new URLSearchParams(Object.entries(params).map(([k, v]) => [k, String(v)]))
      : "";
    const res = await fetch(`${apiBase}/api${path}${qs}`, { method: "GET" });
    if (!res.ok) throw new Error(`apiGet ${path} → ${res.status}`);
    return res.json();
  };
}

export function makeCtx(pool: pg.Pool, apiGet: ToolCtx["apiGet"], tokenLabel: string): ToolCtx {
  return { db: pool, apiGet, tokenLabel };
}

// ---------------------------------------------------------------------------
// access log — one mcp_access_log row per tool call
// ---------------------------------------------------------------------------

export type AccessLogEntry = {
  tokenLabel: string;
  tool: string;
  args: unknown;
  status: "ok" | "error";
  responseBytes: number;
  durationMs: number;
};

export type AccessLogSink = (entry: AccessLogEntry) => Promise<void>;

export function makeAccessLogSink(pool: pg.Pool): AccessLogSink {
  return async (e) => {
    await pool.query(
      "INSERT INTO uw_scan.mcp_access_log " +
        "(token_label, tool, args, status, response_bytes, duration_ms) " +
        "VALUES ($1, $2, $3, $4, $5, $6)",
      [
        e.tokenLabel,
        e.tool,
        e.args === undefined ? null : JSON.stringify(e.args),
        e.status,
        e.responseBytes,
        e.durationMs,
      ],
    );
  };
}

/** Wrap a McpTool handler: time it, byte-count the payload, log ok|error. */
export function wrapToolHandler(
  tool: McpTool,
  ctx: ToolCtx,
  log: AccessLogSink,
): (args: unknown) => Promise<CallToolResult> {
  return async (args) => {
    const started = Date.now();
    let status: AccessLogEntry["status"] = "ok";
    let payload: unknown;
    try {
      payload = await tool.handler(args as Record<string, unknown>, ctx);
      const result: CallToolResult = {
        content: [{ type: "text", text: JSON.stringify(payload) }],
      };
      if (payload !== null && typeof payload === "object" && !Array.isArray(payload)) {
        result.structuredContent = payload as Record<string, unknown>;
      }
      return result;
    } catch (err) {
      status = "error";
      throw err;
    } finally {
      const entry: AccessLogEntry = {
        tokenLabel: ctx.tokenLabel,
        tool: tool.name,
        args,
        status,
        responseBytes:
          payload === undefined ? 0 : Buffer.byteLength(JSON.stringify(payload)),
        durationMs: Date.now() - started,
      };
      try {
        await log(entry);
      } catch (err) {
        console.error("mcp_access_log write failed", err);
      }
    }
  };
}

// ---------------------------------------------------------------------------
// server + sessions
// ---------------------------------------------------------------------------

export function buildMcpServer(ctx: ToolCtx, log: AccessLogSink): McpServer {
  const server = new McpServer({ name: "argon-mcp", version: "0.1.0" });
  for (const tool of TOOLS) {
    server.registerTool(
      tool.name,
      { description: tool.description, inputSchema: tool.inputSchema },
      wrapToolHandler(tool, ctx, log),
    );
  }
  return server;
}

export type Session = {
  transport: StreamableHTTPServerTransport;
  server: McpServer;
  ctx: ToolCtx;
  label: string;
  lastSeen: number;
  /** A live standalone SSE stream keeps its session alive past the idle limit. */
  sseOpen: boolean;
};

export class SessionStore {
  constructor(
    private readonly now: () => number = Date.now,
    private readonly idleMs: number = SESSION_IDLE_MS,
  ) {}

  private sessions = new Map<string, Session>();

  get(id: string): Session | undefined {
    return this.sessions.get(id);
  }

  set(id: string, session: Session): void {
    this.sessions.set(id, session);
  }

  touch(id: string): void {
    const s = this.sessions.get(id);
    if (s) s.lastSeen = this.now();
  }

  delete(id: string): void {
    this.sessions.delete(id);
  }

  get size(): number {
    return this.sessions.size;
  }

  /** Close + drop every session idle past idleMs; live SSE streams exempt. */
  sweep(): void {
    const t = this.now();
    for (const [sid, s] of this.sessions) {
      if (s.sseOpen || t - s.lastSeen <= this.idleMs) continue;
      this.sessions.delete(sid);
      void s.transport
        .close()
        .catch((err) => console.error(`session ${sid} close failed`, err));
    }
  }
}

export type HandlerDeps = {
  pool: pg.Pool;
  labelForToken: LabelForToken;
  apiGet: ToolCtx["apiGet"];
};

export type HandlerOptions = {
  now?: () => number;
  sessionIdleMs?: number;
  sessionSweepMs?: number;
};

function writeJson(res: ServerResponse, status: number, body: unknown): void {
  res.writeHead(status, { "Content-Type": "application/json" });
  res.end(JSON.stringify(body));
}

async function readJsonBody(req: IncomingMessage): Promise<unknown> {
  const chunks: Buffer[] = [];
  let size = 0;
  for await (const chunk of req) {
    size += (chunk as Buffer).length;
    if (size > MAX_BODY_BYTES) throw new Error("payload_too_large");
    chunks.push(chunk as Buffer);
  }
  if (!chunks.length) return undefined;
  return JSON.parse(Buffer.concat(chunks).toString("utf8"));
}

function isInitialize(body: unknown): boolean {
  const msgs = Array.isArray(body) ? body : [body];
  return msgs.some((m) => isInitializeRequest(m));
}

export function makeRequestHandler(deps: HandlerDeps, opts: HandlerOptions = {}) {
  const now = opts.now ?? Date.now;
  const store = new SessionStore(now, opts.sessionIdleMs ?? SESSION_IDLE_MS);
  const sweeper = setInterval(
    () => store.sweep(),
    opts.sessionSweepMs ?? SESSION_SWEEP_MS,
  );
  sweeper.unref(); // never keep the process alive for cleanup work

  return async (req: IncomingMessage, res: ServerResponse): Promise<void> => {
    try {
      const url = new URL(req.url ?? "/", "http://internal");
      if (req.method === "GET" && url.pathname === HEALTHZ_PATH) {
        writeJson(res, 200, { ok: true });
        return;
      }
      if (url.pathname !== MCP_PATH) {
        writeJson(res, 404, { error: "not found" });
        return;
      }
      const token = parseBearer(req);
      const label = token ? await deps.labelForToken(token) : null;
      if (!label) {
        res.writeHead(401, {
          "Content-Type": "application/json",
          "WWW-Authenticate": 'Bearer realm="argon-mcp"',
        });
        res.end(JSON.stringify({ error: "unauthorized" }));
        return;
      }

      const sessionId = req.headers["mcp-session-id"] as string | undefined;
      const session = sessionId ? store.get(sessionId) : undefined;
      if (sessionId && !session) {
        writeJson(res, 404, { error: "unknown session" });
        return;
      }
      if (session && session.label !== label) {
        writeJson(res, 403, { error: "session belongs to a different token" });
        return;
      }
      if (sessionId) store.touch(sessionId);

      if (req.method === "POST") {
        const body = await readJsonBody(req);
        if (session) {
          await session.transport.handleRequest(req, res, body);
          return;
        }
        if (sessionId || !isInitialize(body)) {
          writeJson(res, 400, { error: "missing or invalid session" });
          return;
        }
        // New session: ctx binds this bearer label to every tool call on it.
        const ctx = makeCtx(deps.pool, deps.apiGet, label);
        const server = buildMcpServer(ctx, makeAccessLogSink(deps.pool));
        const transport = new StreamableHTTPServerTransport({
          sessionIdGenerator: () => randomUUID(),
          onsessioninitialized: (sid) => {
            store.set(sid, record);
          },
        });
        const record: Session = {
          transport,
          server,
          ctx,
          label,
          lastSeen: now(),
          sseOpen: false,
        };
        transport.onclose = () => {
          if (transport.sessionId) store.delete(transport.sessionId);
        };
        await server.connect(transport);
        await transport.handleRequest(req, res, body);
        return;
      }

      if (req.method === "GET") {
        if (!session) {
          writeJson(res, 400, { error: "missing session" });
          return;
        }
        // Standalone SSE stream: events fan-out + keepalive. send() delivers a
        // JSON-RPC notification to this stream; close() ends it so the client
        // reconnects (f74bfb6d). Missed events stay in mcp_event via get_events.
        const send = (event: unknown) => {
          void session.transport
            .send({ jsonrpc: "2.0", method: SSE_EVENT_METHOD, params: { event } })
            .catch((err) => console.error("sse send failed", err));
        };
        const close = () => session.transport.closeStandaloneSSEStream();
        let unsubscribe: (() => void) | undefined;
        try {
          unsubscribe = await subscribeEvents(session.ctx, send, close);
        } catch (err) {
          console.error("subscribeEvents failed", err);
        }
        const keepalive = setInterval(() => {
          try {
            res.write(": keepalive\n\n");
          } catch {
            clearInterval(keepalive);
          }
        }, SSE_KEEPALIVE_MS);
        session.sseOpen = true; // a live stream exempts the session from sweeps
        res.on("close", () => {
          session.sseOpen = false;
          session.lastSeen = now(); // dead-socket sessions become sweepable from now
          clearInterval(keepalive);
          unsubscribe?.();
        });
        await session.transport.handleRequest(req, res);
        return;
      }

      if (req.method === "DELETE") {
        if (!session) {
          writeJson(res, 400, { error: "missing session" });
          return;
        }
        await session.transport.handleRequest(req, res); // onclose drops the session
        return;
      }

      writeJson(res, 405, { error: "method not allowed" });
    } catch (err) {
      console.error("request failed", err);
      if (!res.headersSent) {
        const status = err instanceof Error && err.message === "payload_too_large" ? 413 : 500;
        writeJson(res, status, { error: "internal error" });
      }
      if (!res.writableEnded) res.end();
    }
  };
}

// ---------------------------------------------------------------------------

export async function main(): Promise<void> {
  const databaseUrl = process.env.MCP_DATABASE_URL;
  if (!databaseUrl) throw new Error("MCP_DATABASE_URL is required");
  const apiBase = process.env.ARGON_API_URL ?? "http://api:8400";
  const port = Number(process.env.MCP_PORT ?? 8500);

  const pool = new pg.Pool({ connectionString: databaseUrl });
  const handler = makeRequestHandler({
    pool,
    labelForToken: makeLabelForToken(pool),
    apiGet: makeApiGet(apiBase),
  });
  const http = createServer(handler);
  await new Promise<void>((resolve) => http.listen(port, resolve));
  console.log(`argon-mcp listening on :${port} (api: ${apiBase})`);
}

// Direct-run guard: vitest imports this module without starting the listener;
// the esbuild bundle runs it as argv[1].
if (process.argv[1] && import.meta.url === pathToFileURL(process.argv[1]).href) {
  void main();
}
