import { describe, expect, it } from "vitest";

import { sma, tileDomain, velocity } from "@/lib/magnetTiles";
import { SPY_BARS } from "../unit/fixtures/spyBars";

const closes = SPY_BARS.map((b) => b.close);

describe("sma", () => {
  it("is null until the window fills, then averages exactly", () => {
    const out = sma([1, 2, 3, 4], 3);
    expect(out.slice(0, 2)).toEqual([null, null]);
    expect(out[2]).toBeCloseTo(2, 12);
    expect(out[3]).toBeCloseTo(3, 12);
  });

  it("matches a recomputed window on real SPY volume", () => {
    const vols = SPY_BARS.map((b) => b.volume);
    const out = sma(vols, 20);
    const i = vols.length - 1;
    const want = vols.slice(i - 19, i + 1).reduce((a, b) => a + b, 0) / 20;
    expect(out[i]!).toBeCloseTo(want, 6);
  });

  it("does not let one bad bar poison every later value", () => {
    // A running sum that admitted NaN would never recover — every subsequent
    // entry would be NaN, and an NaN in an SVG `d` silently drops the path.
    const out = sma([1, NaN, 3, 4, 5], 2);
    expect(out.every((v) => v === null || Number.isFinite(v))).toBe(true);
  });

  it("rejects a nonsense window instead of returning garbage", () => {
    expect(() => sma([1, 2, 3], 0)).toThrow(RangeError);
  });
});

describe("velocity", () => {
  it("recovers a known compound rate", () => {
    // 100 -> 121 over 2 sessions is exactly 10%/session.
    expect(velocity([100, 110, 121], 0, 2)).toBeCloseTo(10, 10);
  });

  it("is signed and reads as percent per session on real SPY closes", () => {
    const n = closes.length;
    const v = velocity(closes, n - 6, n - 1)!;
    expect(Number.isFinite(v)).toBe(true);
    // Sanity: SPY does not move 20%/day. Catches a units slip (fraction vs %).
    expect(Math.abs(v)).toBeLessThan(20);
    const direction = closes[n - 1]! >= closes[n - 6]! ? 1 : -1;
    expect(Math.sign(v)).toBe(direction);
  });

  it("returns null — never NaN — on every degenerate input", () => {
    expect(velocity(closes, -1, 5)).toBeNull();
    expect(velocity(closes, 0, closes.length)).toBeNull();
    expect(velocity(closes, 5, 5)).toBeNull();
    expect(velocity(closes, 6, 3)).toBeNull();
    // Math.pow(negative, fractional) is NaN — the guard is what stops that
    // reaching the tile as a printed "NaN%/d".
    expect(velocity([-10, 20], 0, 1)).toBeNull();
    expect(velocity([0, 20], 0, 1)).toBeNull();
  });
});

describe("tileDomain", () => {
  it("brackets the data with padding on both sides", () => {
    const d = tileDomain([10, 20, 30])!;
    expect(d.lo).toBeLessThan(10);
    expect(d.hi).toBeGreaterThan(30);
  });

  it("pulls zero into frame when asked, and not otherwise", () => {
    expect(tileDomain([5, 8, 9])!.lo).toBeGreaterThan(0);
    expect(
      tileDomain([5, 8, 9], { includeZero: true })!.lo,
    ).toBeLessThanOrEqual(0);
  });

  it("never returns a zero-width domain, even when flat", () => {
    for (const flat of [
      [7, 7, 7],
      [0, 0, 0],
      [-3, -3],
    ]) {
      const d = tileDomain(flat)!;
      expect(d.hi).toBeGreaterThan(d.lo);
    }
  });

  it("ignores non-finite values and needs two real points", () => {
    expect(tileDomain([1, null, undefined, NaN, 5])!.hi).toBeGreaterThan(5);
    expect(tileDomain([1])).toBeNull();
    expect(tileDomain([1, null])).toBeNull();
    expect(tileDomain([])).toBeNull();
  });
});
