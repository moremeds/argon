import { z } from "zod";

import type { McpTool } from "../types";

// Drain unread events for this token inside ONE transaction: the
// INSERT..ON CONFLICT RETURNING locks/creates the cursor row (concurrent calls
// for one token serialize), then SELECT id > cursor ORDER BY id LIMIT limit+1
// — the extra row only detects `more` and is NOT delivered, so the cursor must
// advance to the max RETURNED id, never past it. The UPDATE only runs when
// rows came back. argon_mcp may write mcp_event_cursor and nothing else.
const inputSchema = {
  limit: z.number().int().min(1).max(500).default(100),
};
const argsSchema = z.object(inputSchema);

type EventRow = {
  id: string;
  kind: string;
  subject: string;
  basis: string;
  payload: unknown;
  emitted_at: unknown;
};

export const tool: McpTool = {
  name: "get_events",
  description:
    "Drain unread MCP events for this token. Once-only delivery: each call " +
    "advances this token's persistent cursor past the events it returns, so an " +
    "event is never returned twice to the same token (a different token has its " +
    "own cursor). SSE subscriptions stream events in real time and do NOT " +
    "advance the cursor — call get_events at the start of each run to catch " +
    "anything missed while offline. Returns { events, cursor, more }: when " +
    "more=true, call again to keep draining.",
  inputSchema,
  handler: async (args, ctx) => {
    // Re-parse inside the handler: the McpTool registry type erases the shape,
    // and this applies the default even if a caller bypasses zod validation.
    const { limit } = argsSchema.parse(args);
    const client = await ctx.db.connect();
    try {
      await client.query("BEGIN");
      const cur = await client.query(
        `INSERT INTO uw_scan.mcp_event_cursor (token_label)
         VALUES ($1)
         ON CONFLICT (token_label) DO UPDATE SET token_label = EXCLUDED.token_label
         RETURNING last_event_id`,
        [ctx.tokenLabel],
      );
      const prevId: string = cur.rows[0].last_event_id;
      const res = await client.query(
        `SELECT id, kind, subject, basis, payload, emitted_at
           FROM uw_scan.mcp_event
          WHERE id > $1
          ORDER BY id
          LIMIT $2`,
        [prevId, limit + 1],
      );
      const more = res.rows.length > limit;
      const events: EventRow[] = res.rows.slice(0, limit);
      let cursor = String(prevId);
      if (events.length > 0) {
        cursor = String(events[events.length - 1].id);
        await client.query(
          `UPDATE uw_scan.mcp_event_cursor
              SET last_event_id = $1, updated_at = now()
            WHERE token_label = $2`,
          [cursor, ctx.tokenLabel],
        );
      }
      await client.query("COMMIT");
      return {
        events: events.map((r) => ({ ...r, id: String(r.id) })),
        cursor,
        more,
      };
    } catch (err) {
      await client.query("ROLLBACK").catch(() => {});
      throw err;
    } finally {
      client.release();
    }
  },
};
