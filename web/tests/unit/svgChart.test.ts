import { describe, it, expect } from "vitest";
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromNullablePoints,
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

  describe("pathFromNullablePoints — gap-aware path builder", () => {
    it("returns empty string for empty input", () => {
      expect(pathFromNullablePoints([])).toBe("");
    });

    it("matches pathFromPoints when there are no gaps", () => {
      const pts: [number, number][] = [
        [0, 0],
        [1, 2],
        [2, 4],
      ];
      expect(pathFromNullablePoints(pts)).toBe(pathFromPoints(pts));
    });

    it("emits a fresh M after a null gap", () => {
      const out = pathFromNullablePoints([
        [0, 0],
        [1, 1],
        null,
        [3, 3],
        [4, 4],
      ]);
      expect((out.match(/M/g) ?? []).length).toBe(2);
      expect(out).toContain("M0,0");
      expect(out).toContain("M3,3");
    });

    it("treats consecutive nulls as a single break", () => {
      const out = pathFromNullablePoints([[0, 0], null, null, null, [4, 4]]);
      expect((out.match(/M/g) ?? []).length).toBe(2);
    });

    it("breaks on non-finite coordinates too", () => {
      const out = pathFromNullablePoints([
        [0, 0],
        [1, Number.NaN],
        [2, 2],
      ]);
      expect((out.match(/M/g) ?? []).length).toBe(2);
      expect(out).not.toContain("NaN");
    });

    it("skips a leading null without emitting an empty M", () => {
      const out = pathFromNullablePoints([null, [1, 1], [2, 2]]);
      expect((out.match(/M/g) ?? []).length).toBe(1);
      expect(out.startsWith("M1,1")).toBe(true);
    });
  });
});
