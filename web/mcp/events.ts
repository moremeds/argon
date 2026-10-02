import type { PoolClient } from "pg";

import type { EventStreamHook, ToolCtx } from "./types";

// Owner: C (hub refactor: Astra fix — one dedicated LISTEN client total, NOT
// one pool connection per subscriber; in-process fan-out). The client is
// checked out lazily on the first subscriber and RELEASED when the last one
// leaves — no idle connection is held when nobody listens.
//
// Contract (see types.ts): no reconnect logic here. On client 'error' every
// subscriber's close() fires; server.ts ends those streams and each client's
// reconnect re-invokes this hook, which re-creates the hub. Missed events
// stay readable via get_events — SSE never advances the cursor.

type Subscriber = {
  send: (event: unknown) => void;
  close: () => void;
};

type Hub = {
  client: PoolClient;
  subs: Set<Subscriber>;
  /** Serializes per-notification SELECTs so fan-out order stays == id order. */
  chain: Promise<void>;
};

let hub: Hub | null = null;
let starting: Promise<Hub> | null = null;

function onNotification(
  h: Hub,
  msg: { channel?: string; payload?: string },
): void {
  if (msg.channel !== "mcp_event" || msg.payload == null) return;
  const id = msg.payload;
  h.chain = h.chain
    .then(async () => {
      const res = await h.client.query(
        `SELECT id, kind, subject, basis, payload, emitted_at
           FROM uw_scan.mcp_event
          WHERE id = $1`,
        [id],
      );
      const row = res.rows[0];
      if (row) {
        for (const s of [...h.subs]) s.send({ ...row, id: String(row.id) });
      }
    })
    .catch(() => {
      // A failed fetch only drops the push; get_events replays it.
    });
}

function teardown(h: Hub, err?: Error): void {
  if (hub !== h) return; // already torn down
  hub = null;
  for (const s of [...h.subs]) s.close(); // end every subscriber stream
  h.subs.clear();
  try {
    h.client.release(err);
  } catch {
    // already released
  }
}

async function startHub(ctx: ToolCtx): Promise<Hub> {
  if (hub) return hub;
  starting ??= (async () => {
    const client = await ctx.db.connect();
    const h: Hub = { client, subs: new Set(), chain: Promise.resolve() };
    client.on("notification", (m: { channel?: string; payload?: string }) =>
      onNotification(h, m),
    );
    client.on("error", (err: Error) => teardown(h, err));
    try {
      await client.query("LISTEN mcp_event");
    } catch (err) {
      try {
        client.release(err instanceof Error ? err : new Error(String(err)));
      } catch {
        // already released
      }
      throw err;
    }
    hub = h;
    return h;
  })().finally(() => {
    starting = null;
  });
  return starting;
}

export const subscribeEvents: EventStreamHook = async (ctx, send, close) => {
  const sub: Subscriber = { send, close };
  const h = await startHub(ctx);
  h.subs.add(sub);

  let active = true;
  return () => {
    if (!active) return;
    active = false;
    h.subs.delete(sub);
    if (h.subs.size === 0 && hub === h) {
      // Last subscriber left → UNLISTEN + release the dedicated client; the
      // next subscriber starts a fresh hub.
      hub = null;
      void (async () => {
        try {
          await h.client.query("UNLISTEN mcp_event");
        } finally {
          try {
            h.client.release();
          } catch {
            // already released
          }
        }
      })().catch(() => {});
    }
  };
};

/** Vitest hook: drop the module-level hub between tests. */
export function resetEventsHubForTests(): void {
  if (hub) {
    for (const s of [...hub.subs]) s.close();
    try {
      hub.client.release();
    } catch {
      // already released
    }
  }
  hub = null;
  starting = null;
}
