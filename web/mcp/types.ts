// Agent MCP contracts — see docs/superpowers/specs/2026-10-02-agent-mcp-design.md.
// Changes to these types go through the lead session (argon-2e).
import type { Pool } from "pg";
import type { z } from "zod";

export type ToolCtx = {
  /** Pool connected as the read-only `argon_mcp` role. */
  db: Pool;
  /** GET-only call to the internal FastAPI (`/api` prefix implied). */
  apiGet: (path: string, params?: Record<string, string | number | boolean>) => Promise<unknown>;
  tokenLabel: string;
};

export type McpTool<S extends z.ZodRawShape = z.ZodRawShape> = {
  name: string;
  description: string;
  inputSchema: S;
  handler: (args: z.infer<z.ZodObject<S>>, ctx: ToolCtx) => Promise<unknown>;
};

/**
 * Registry element type. A tool with REQUIRED args is McpTool<typeof shape>; it is not
 * assignable to the default McpTool (handler params are contravariant), so the registry
 * erases the shape here instead of forcing every arg to be optional.
 */
// eslint-disable-next-line @typescript-eslint/no-explicit-any
export type AnyMcpTool = McpTool<any>;

/** Bulk-tool response shape. */
export type Columnar = {
  as_of: { eod: string | null; live: string | null };
  columns: string[];
  rows: unknown[][];
};

/**
 * SSE fan-out hook: server.ts calls it once per open subscription; return an unsubscribe fn.
 * On an unrecoverable error (e.g. pg client error) the hook releases its resources and calls
 * `close()`; server.ts then ends the SSE stream and the client reconnects. Missed events stay
 * readable via `get_events` (SSE never advances the cursor).
 */
export type EventStreamHook = (
  ctx: ToolCtx,
  send: (event: unknown) => void,
  close: () => void,
) => Promise<() => void>;
