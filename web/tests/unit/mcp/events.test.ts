import { EventEmitter } from "node:events";

import { beforeEach, describe, expect, it, vi } from "vitest";

import { resetEventsHubForTests, subscribeEvents } from "../../../mcp/events";
import type { ToolCtx } from "../../../mcp/types";

type Query = { text: string; params?: unknown[] };

// Fake dedicated listener client: one pg.Client checked out once per hub.
class FakeClient extends EventEmitter {
  queries: Query[] = [];
  releasedWith: (Error | undefined)[] = [];
  selectRows: Record<string, unknown>[] = [];

  async query(text: string, params?: unknown[]) {
    this.queries.push({ text, params });
    if (text.startsWith("SELECT")) return { rows: this.selectRows };
    return { rows: [] };
  }

  release(err?: Error) {
    this.releasedWith.push(err);
  }
}

function ctx(client: FakeClient, connect?: ReturnType<typeof vi.fn>): ToolCtx {
  return {
    db: {
      connect: connect ?? vi.fn(async () => client),
    } as unknown as ToolCtx["db"],
    apiGet: async () => ({}),
    tokenLabel: "t",
  };
}

const event = {
  id: "9",
  kind: "cri",
  subject: "global",
  basis: null,
  payload: {},
  emitted_at: new Date("2026-01-01T00:00:00Z"),
};

beforeEach(() => {
  resetEventsHubForTests();
});

describe("subscribeEvents hub", () => {
  it("checks out ONE dedicated client, LISTENs once", async () => {
    const c = new FakeClient();
    const connect = vi.fn(async () => c);
    const un1 = await subscribeEvents(ctx(c, connect), vi.fn(), vi.fn());
    expect(connect).toHaveBeenCalledTimes(1);
    expect(c.queries[0]?.text).toBe("LISTEN mcp_event");
    un1();
  });

  it("two subscribers share the single client and fan out", async () => {
    const c = new FakeClient();
    const connect = vi.fn(async () => c);
    const c2 = ctx(c, connect);
    const send1 = vi.fn();
    const send2 = vi.fn();
    const un1 = await subscribeEvents(c2, send1, vi.fn());
    const un2 = await subscribeEvents(c2, send2, vi.fn());
    expect(connect).toHaveBeenCalledTimes(1);
    expect(c.queries.filter((q) => q.text === "LISTEN mcp_event")).toHaveLength(1);

    c.selectRows = [event];
    c.emit("notification", { channel: "mcp_event", payload: "9" });
    await vi.waitFor(() => {
      expect(send1).toHaveBeenCalledWith(event);
      expect(send2).toHaveBeenCalledWith(event);
    });
    // ONE SELECT total — the row is fetched once then fanned out in-process.
    expect(c.queries.filter((q) => q.text.startsWith("SELECT"))).toHaveLength(1);
    un1();
    un2();
  });

  it("unsubscribing one subscriber keeps the hub alive for the other", async () => {
    const c = new FakeClient();
    const c2 = ctx(c);
    const send1 = vi.fn();
    const send2 = vi.fn();
    const un1 = await subscribeEvents(c2, send1, vi.fn());
    const un2 = await subscribeEvents(c2, send2, vi.fn());
    un1();
    expect(c.queries.some((q) => q.text === "UNLISTEN mcp_event")).toBe(false);
    c.selectRows = [event];
    c.emit("notification", { channel: "mcp_event", payload: "9" });
    await vi.waitFor(() => expect(send2).toHaveBeenCalledWith(event));
    expect(send1).not.toHaveBeenCalled();
    un2();
  });

  it("releases the client after the last subscriber leaves (UNLISTEN first)", async () => {
    const c = new FakeClient();
    const un = await subscribeEvents(ctx(c), vi.fn(), vi.fn());
    un();
    await vi.waitFor(() => expect(c.releasedWith).toEqual([undefined]));
    expect(c.queries[1]?.text).toBe("UNLISTEN mcp_event");
  });

  it("client 'error' closes every subscriber stream and releases with err", async () => {
    const c = new FakeClient();
    const c2 = ctx(c);
    const close1 = vi.fn();
    const close2 = vi.fn();
    await subscribeEvents(c2, vi.fn(), close1);
    await subscribeEvents(c2, vi.fn(), close2);
    c.emit("error", new Error("conn dropped"));
    expect(close1).toHaveBeenCalledTimes(1);
    expect(close2).toHaveBeenCalledTimes(1);
    await vi.waitFor(() => expect(c.releasedWith[0]).toBeInstanceOf(Error));
  });

  it("after a hub teardown, the next subscriber starts a fresh hub", async () => {
    const c = new FakeClient();
    await subscribeEvents(ctx(c), vi.fn(), vi.fn());
    c.emit("error", new Error("boom"));
    const c2 = new FakeClient();
    await subscribeEvents(ctx(c2), vi.fn(), vi.fn());
    expect(c2.queries[0]?.text).toBe("LISTEN mcp_event");
  });

  it("ignores other channels and missing payloads", async () => {
    const c = new FakeClient();
    const send = vi.fn();
    const un = await subscribeEvents(ctx(c), send, vi.fn());
    c.emit("notification", { channel: "other", payload: "9" });
    c.emit("notification", { channel: "mcp_event" });
    await Promise.resolve();
    expect(send).not.toHaveBeenCalled();
    un();
  });

  it("unsubscribe is idempotent", async () => {
    const c = new FakeClient();
    const un = await subscribeEvents(ctx(c), vi.fn(), vi.fn());
    un();
    un();
    await vi.waitFor(() => expect(c.releasedWith).toHaveLength(1));
  });

  it("removes listeners before release — reused client never stacks hubs", async () => {
    const c = new FakeClient();
    const c2 = ctx(c, vi.fn(async () => c));
    const base = c.listenerCount("notification");
    // Three subscribe/unsubscribe cycles on the same pooled client.
    for (let i = 0; i < 3; i++) {
      const un = await subscribeEvents(c2, vi.fn(), vi.fn());
      un();
      await vi.waitFor(() =>
        expect(c.listenerCount("notification")).toBe(base),
      );
    }
    // The 4th hub is the ONLY one listening: one notification → one SELECT.
    const send = vi.fn();
    await subscribeEvents(c2, send, vi.fn());
    c.selectRows = [event];
    c.emit("notification", { channel: "mcp_event", payload: "9" });
    await vi.waitFor(() => expect(send).toHaveBeenCalledWith(event));
    expect(c.queries.filter((q) => q.text.startsWith("SELECT"))).toHaveLength(1);
    expect(c.listenerCount("error")).toBe(1); // one hub's worth, not four
  });
});
