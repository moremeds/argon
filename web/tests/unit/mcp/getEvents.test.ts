import { describe, expect, it, vi } from "vitest";
import type { Pool } from "pg";

import { tool } from "@/mcp/tools/get_events";

type Query = { text: string; params?: unknown[] };

/** Records statements in order; canned rows per statement kind. */
class FakeClient {
  queries: Query[] = [];
  releaseCount = 0;
  cursorId = "0";
  eventRows: Record<string, unknown>[] = [];
  failOn: RegExp | null = null;

  async query(text: string, params?: unknown[]) {
    this.queries.push({ text, params });
    if (this.failOn && this.failOn.test(text)) throw new Error("boom");
    if (text.includes("INSERT INTO uw_scan.mcp_event_cursor")) {
      return { rows: [{ last_event_id: this.cursorId }] };
    }
    if (text.includes("FROM uw_scan.mcp_event")) {
      return { rows: this.eventRows };
    }
    return { rows: [] };
  }

  release() {
    this.releaseCount += 1;
  }
}

const ctx = (client: FakeClient) => ({
  db: { connect: async () => client } as unknown as Pool,
  apiGet: vi.fn(),
  tokenLabel: "t1",
});

const row = (id: string) => ({
  id,
  kind: "cri_regime",
  subject: "CRI",
  basis: "eod",
  payload: { from: "LOW", to: "ELEVATED" },
  emitted_at: "2026-10-02T01:00:00.000Z",
});

describe("get_events", () => {
  it("runs BEGIN → cursor lock → SELECT → UPDATE → COMMIT, cursor advances to max id", async () => {
    const client = new FakeClient();
    client.cursorId = "4";
    client.eventRows = [row("7"), row("9")];

    const out = (await tool.handler({ limit: 100 }, ctx(client))) as {
      events: { id: string }[];
      cursor: string;
      more: boolean;
    };

    const kinds = client.queries.map((q) =>
      q.text === "BEGIN" || q.text === "COMMIT" || q.text === "ROLLBACK"
        ? q.text
        : q.text.match(/^(INSERT|SELECT|UPDATE)/)![0],
    );
    expect(kinds).toEqual(["BEGIN", "INSERT", "SELECT", "UPDATE", "COMMIT"]);

    const insert = client.queries[1];
    expect(insert.params).toEqual(["t1"]);
    const select = client.queries[2];
    expect(select.params).toEqual(["4", 101]); // cursor + limit+1
    const update = client.queries[3];
    expect(update.params).toEqual(["9", "t1"]); // max RETURNED id

    expect(out.events.map((e) => e.id)).toEqual(["7", "9"]);
    expect(out.cursor).toBe("9");
    expect(out.more).toBe(false);
    expect(client.releaseCount).toBe(1);
  });

  it("issues no UPDATE and keeps the cursor when the inbox is empty", async () => {
    const client = new FakeClient();
    client.cursorId = "3";

    const out = (await tool.handler({ limit: 100 }, ctx(client))) as {
      events: unknown[];
      cursor: string;
      more: boolean;
    };

    expect(out).toEqual({ events: [], cursor: "3", more: false });
    const statements = client.queries.map((q) =>
      q.text === "BEGIN" || q.text === "COMMIT"
        ? q.text
        : q.text.match(/^(INSERT|SELECT|UPDATE)/)![0],
    );
    expect(statements).toEqual(["BEGIN", "INSERT", "SELECT", "COMMIT"]);
    expect(client.releaseCount).toBe(1);
  });

  it("sets more=true at limit+1 and advances the cursor only to the last returned id", async () => {
    const client = new FakeClient();
    client.eventRows = [row("5"), row("6")]; // limit 1 → second row is lookahead only

    const out = (await tool.handler({ limit: 1 }, ctx(client))) as {
      events: { id: string }[];
      cursor: string;
      more: boolean;
    };

    expect(out.events.map((e) => e.id)).toEqual(["5"]);
    expect(out.cursor).toBe("5"); // NOT "6" — the lookahead row stays unread
    expect(out.more).toBe(true);
    const update = client.queries.find((q) => q.text.startsWith("UPDATE"))!;
    expect(update.params).toEqual(["5", "t1"]);
  });

  it("ROLLBACKs and releases when a statement fails", async () => {
    const client = new FakeClient();
    client.failOn = /FROM uw_scan\.mcp_event/;

    await expect(tool.handler({ limit: 5 }, ctx(client))).rejects.toThrow("boom");
    expect(client.queries.at(-1)?.text).toBe("ROLLBACK");
    expect(client.queries.map((q) => q.text)).not.toContain("COMMIT");
    expect(client.releaseCount).toBe(1);
  });
});
