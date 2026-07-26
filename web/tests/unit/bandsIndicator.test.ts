import { describe, expect, it } from "vitest";
import { contiguousValidRuns } from "@/lib/lwc/bandsIndicator";

describe("contiguousValidRuns", () => {
  it("finds no runs in an all-gap array", () => {
    expect(contiguousValidRuns([{ upper: null }, { upper: null }])).toEqual([]);
  });

  it("drops an isolated single valid point (can't draw a region from one)", () => {
    expect(
      contiguousValidRuns([{ upper: null }, { upper: 1 }, { upper: null }]),
    ).toEqual([]);
  });

  it("returns the whole array as one run when nothing is a gap", () => {
    expect(
      contiguousValidRuns([{ upper: 1 }, { upper: 2 }, { upper: 3 }]),
    ).toEqual([[0, 2]]);
  });

  it("splits into separate runs around a mid-series gap", () => {
    const points = [
      { upper: 1 },
      { upper: 2 },
      { upper: null }, // the gap
      { upper: 3 },
      { upper: 4 },
      { upper: 5 },
    ];
    expect(contiguousValidRuns(points)).toEqual([
      [0, 1],
      [3, 5],
    ]);
  });

  it("drops leading/trailing warm-up gaps but keeps the middle run", () => {
    const points = [
      { upper: null },
      { upper: null },
      { upper: 1 },
      { upper: 2 },
      { upper: null },
    ];
    expect(contiguousValidRuns(points)).toEqual([[2, 3]]);
  });
});
