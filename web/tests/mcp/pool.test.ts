// makePool semantics — plain numbered tasks, no market data.
import { describe, expect, it } from "vitest";
import { makePool } from "@/mcp/lib/pool";

describe("makePool", () => {
  it("caps concurrent tasks at the limit", async () => {
    const limit = makePool(3);
    let inflight = 0;
    let max = 0;
    await Promise.all(
      Array.from({ length: 20 }, (_, i) =>
        limit(async () => {
          inflight++;
          max = Math.max(max, inflight);
          await new Promise((r) => setTimeout(r, 1));
          inflight--;
          return i;
        }),
      ),
    );
    expect(max).toBe(3);
  });

  it("starts waiters in FIFO order", async () => {
    const limit = makePool(2);
    const started: number[] = [];
    let open!: () => void;
    const gate = new Promise<void>((r) => {
      open = r;
    });
    // Two blockers occupy both slots until the gate opens.
    const blockers = [0, 1].map((i) =>
      limit(async () => {
        started.push(i);
        await gate;
      }),
    );
    // Four waiters queue behind; each records its start index.
    const waiters = [2, 3, 4, 5].map((i) =>
      limit(async () => {
        started.push(i);
      }),
    );
    // Let the blockers' fns run so the waiters are actually queued.
    await new Promise((r) => setTimeout(r, 0));
    expect(started).toEqual([0, 1]);
    open();
    await Promise.all([...blockers, ...waiters]);
    expect(started).toEqual([0, 1, 2, 3, 4, 5]);
  });

  it("releases the slot when fn rejects", async () => {
    const limit = makePool(1);
    await expect(
      limit(async () => {
        throw new Error("boom");
      }),
    ).rejects.toThrow("boom");
    // The slot was freed — the next task runs.
    await expect(limit(async () => 42)).resolves.toBe(42);

    // A queued waiter still proceeds after the holder rejects.
    let release!: () => void;
    const gate = new Promise<void>((r) => {
      release = r;
    });
    const p1 = limit(async () => {
      await gate;
      throw new Error("late");
    });
    const p2 = limit(async () => "after");
    release();
    await expect(p1).rejects.toThrow("late");
    await expect(p2).resolves.toBe("after");
  });

  it("rejects a limit below 1", () => {
    expect(() => makePool(0)).toThrow(RangeError);
  });
});
