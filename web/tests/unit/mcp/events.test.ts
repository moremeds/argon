import { EventEmitter } from "node:events";

import { describe, expect, it, vi } from "vitest";
import type { Pool } from "pg";

import { subscribeEvents } from "@/mcp/events";
import type { ToolCtx } from "@/mcp/types";

type Query = { text: string; params?: unknown[] };

/** EventEmitter so the hook's .on("notification"/"error") wiring is real. */
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

const ctx = (client: FakeClient): ToolCtx => ({
  db: { connect: async () => client } as unknown as Pool,
  apiGet: vi.fn(),
  tokenLabel: "t1",
});

const eventRow = (id: string) => ({
  id,
  kind: "cri_regime",
  subject: "CRI",
  basis: "eod",
  payload: { from: "LOW", to: "ELEVATED" },
  emitted_at: "2026-10-02T01:00:00.000Z",
});

describe("subscribeEvents", () => {
  it("issues LISTEN on a dedicated client before returning", async () => {
    const client = new FakeClient();
    await subscribeEvents(ctx(client), vi.fn(), vi.fn());
    expect(client.queries.map((q) => q.text)).toEqual(["LISTEN mcp_event"]);
    expect(client.releasedWith).toEqual([]);
  });

  it("notification → SELECT by id → send(row) with string id, unwrapped", async () => {
    const client = new FakeClient();
    client.selectRows = [eventRow("42")];
    const send = vi.fn();
    const close = vi.fn();
    await subscribeEvents(ctx(client), send, close);

    client.emit("notification", { channel: "mcp_event", payload: "42" });
    await vi.waitFor(() => expect(send).toHaveBeenCalledTimes(1));

    const select = client.queries.find((q) => q.text.startsWith("SELECT"))!;
    expect(select.text).toContain("FROM uw_scan.mcp_event");
    expect(select.params).toEqual(["42"]);
    expect(send).toHaveBeenCalledWith({
      id: "42",
      kind: "cri_regime",
      subject: "CRI",
      basis: "eod",
      payload: { from: "LOW", to: "ELEVATED" },
      emitted_at: "2026-10-02T01:00:00.000Z",
    });
    expect(close).not.toHaveBeenCalled();
  });

  it("ignores notifications on other channels or without payload", async () => {
    const client = new FakeClient();
    const send = vi.fn();
    await subscribeEvents(ctx(client), send, vi.fn());

    client.emit("notification", { channel: "other", payload: "1" });
    client.emit("notification", { channel: "mcp_event", payload: null });
    await Promise.resolve();

    expect(client.queries.filter((q) => q.text.startsWith("SELECT"))).toEqual([]);
    expect(send).not.toHaveBeenCalled();
  });

  it("on client error: releases with the error and calls close()", async () => {
    const client = new FakeClient();
    const close = vi.fn();
    await subscribeEvents(ctx(client), vi.fn(), close);

    const boom = new Error("conn died");
    client.emit("error", boom);

    expect(client.releasedWith).toEqual([boom]);
    expect(close).toHaveBeenCalledTimes(1);
  });

  it("unsubscribe = UNLISTEN then release, and is idempotent", async () => {
    const client = new FakeClient();
    const close = vi.fn();
    const unsub = await subscribeEvents(ctx(client), vi.fn(), close);

    unsub();
    await vi.waitFor(() => expect(client.releasedWith).toEqual([undefined]));
    unsub(); // second call is a no-op

    const unlistens = client.queries.filter((q) =>
      q.text.includes("UNLISTEN"),
    );
    expect(unlistens).toHaveLength(1);
    expect(client.releasedWith).toEqual([undefined]);
    expect(close).not.toHaveBeenCalled();
  });

  it("unsubscribe after an error teardown is a no-op", async () => {
    const client = new FakeClient();
    const close = vi.fn();
    const unsub = await subscribeEvents(ctx(client), vi.fn(), close);

    client.emit("error", new Error("boom"));
    unsub();
    await Promise.resolve();

    expect(client.queries.filter((q) => q.text.includes("UNLISTEN"))).toEqual(
      [],
    );
    expect(client.releasedWith).toHaveLength(1);
  });
});
