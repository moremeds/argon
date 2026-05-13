import { describe, it, expect } from "vitest";
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
} from "@/lib/svgChart";

describe("svgChart helpers", () => {
  it("linearScale maps domain to range", () => {
    const s = linearScale([0, 100], [0, 200]);
    expect(s(0)).toBe(0);
    expect(s(50)).toBe(100);
    expect(s(100)).toBe(200);
  });

  it("pathFromPoints emits M/L commands", () => {
    expect(
      pathFromPoints([
        [0, 0],
        [10, 10],
      ]),
    ).toBe("M0,0 L10,10");
  });

  it("pathFromPoints returns empty for no points", () => {
    expect(pathFromPoints([])).toBe("");
  });

  it("niceTicks returns round numbers spanning the range", () => {
    const ticks = niceTicks(0, 100, 5);
    expect(ticks.length).toBeGreaterThanOrEqual(2);
    expect(ticks[0]).toBeLessThanOrEqual(0);
    expect(ticks[ticks.length - 1]).toBeGreaterThanOrEqual(100);
  });

  describe("finiteDomain — NaN-safety helper", () => {
    it("returns min/max of finite values only", () => {
      const d = finiteDomain([1, NaN, 2, null, 3, undefined, 5] as number[]);
      expect(d).toEqual({ lo: 1, hi: 5, count: 4 });
    });

    it("returns null when fewer than two finite values", () => {
      expect(finiteDomain([])).toBeNull();
      expect(finiteDomain([NaN, null] as unknown as number[])).toBeNull();
      expect(finiteDomain([5])).toBeNull();
    });

    it("treats Infinity as non-finite", () => {
      expect(finiteDomain([Infinity, -Infinity, 1, 2])).toEqual({
        lo: 1,
        hi: 2,
        count: 2,
      });
    });
  });
});
