import { describe, expect, it } from "vitest";
import { bucketFreshness } from "@/lib/freshness";

describe("bucketFreshness", () => {
  const now = new Date("2026-05-12T14:00:00Z");
  it("fresh within 60 min", () => {
    expect(bucketFreshness("2026-05-12T13:55:00Z", now)).toBe("fresh");
  });
  it("stale between 60 and 180 min", () => {
    expect(bucketFreshness("2026-05-12T12:00:00Z", now)).toBe("stale");
  });
  it("dead beyond 180 min", () => {
    expect(bucketFreshness("2026-05-12T05:00:00Z", now)).toBe("dead");
  });
  it("accepts scanner-specific thresholds", () => {
    expect(
      bucketFreshness("2026-05-11T14:00:00Z", now, {
        freshMinutes: 8 * 60,
        staleMinutes: 72 * 60,
      }),
    ).toBe("stale");
  });
  it("treats nulls as dead", () => {
    expect(bucketFreshness(null, now)).toBe("dead");
  });
  it("treats invalid ISO strings as dead", () => {
    expect(bucketFreshness("not-a-date", now)).toBe("dead");
  });
});
