import type { EventStreamHook } from "./types";

// Owner: C. LISTEN mcp_event on a DEDICATED ctx.db.connect() client (a Pool
// conn cannot LISTEN and serve queries at once without pinning). On each
// notification, SELECT the row by id and send() it unwrapped — server.ts's
// send already produces the JSON-RPC notification envelope.
//
// Contract (see types.ts): no reconnect logic here. On a client 'error' the
// hook releases the client with the error and calls close(); server.ts ends
// the stream and the client's reconnect re-invokes this hook. Missed events
// stay recoverable via get_events — SSE never advances the cursor.
export const subscribeEvents: EventStreamHook = async (ctx, send, close) => {
  const client = await ctx.db.connect();
  let torn = false;

  const release = (err?: Error) => {
    try {
      client.release(err);
    } catch {
      // already released
    }
  };

  // Serialize the per-notification SELECTs so send() order stays == id order.
  let chain: Promise<void> = Promise.resolve();
  const onNotification = (msg: { channel?: string; payload?: string }) => {
    if (msg.channel !== "mcp_event" || msg.payload == null) return;
    const id = msg.payload;
    chain = chain
      .then(async () => {
        const res = await client.query(
          `SELECT id, kind, subject, basis, payload, emitted_at
             FROM uw_scan.mcp_event
            WHERE id = $1`,
          [id],
        );
        const row = res.rows[0];
        if (row) send({ ...row, id: String(row.id) });
      })
      .catch(() => {
        // A failed fetch only drops the push; get_events replays it.
      });
  };

  const onError = (err: Error) => {
    if (torn) return;
    torn = true;
    client.off("notification", onNotification);
    release(err);
    close();
  };

  try {
    client.on("notification", onNotification);
    client.on("error", onError);
    await client.query("LISTEN mcp_event");
  } catch (err) {
    torn = true;
    release(err instanceof Error ? err : new Error(String(err)));
    throw err;
  }

  // Idempotent: UNLISTEN once, then release once. A dead client skips UNLISTEN
  // via 'error' teardown above; an UNLISTEN that fails still releases.
  return () => {
    if (torn) return;
    torn = true;
    client.off("notification", onNotification);
    client.off("error", onError);
    void (async () => {
      try {
        await client.query("UNLISTEN mcp_event");
      } finally {
        release();
      }
    })().catch(() => {});
  };
};
