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

/** Bulk-tool response shape. */
export type Columnar = {
  as_of: { eod: string | null; live: string | null };
  columns: string[];
  rows: unknown[][];
};

/** SSE fan-out hook: server.ts calls it once per open subscription; return an unsubscribe fn. */
export type EventStreamHook = (
  ctx: ToolCtx,
  send: (event: unknown) => void,
) => Promise<() => void>;
