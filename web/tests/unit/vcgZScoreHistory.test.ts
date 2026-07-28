import { describe, expect, it } from "vitest";

import { selectZSeries } from "@/components/regime/vcg/VcgZScoreHistoryChart";
import { pathFromPointsSmooth, type Point } from "@/lib/svgChart";

// eslint-disable-next-line @typescript-eslint/no-explicit-any
const row = (date: string, vcg: number | null) => ({ date, vcg }) as any;

describe("selectZSeries", () => {
  it("drops null/non-finite vcg, sorts ascending, and takes the tail", () => {
    const out = selectZSeries(
      [
        row("2026-03-03", 1.5),
        row("2026-03-01", 0.5),
        row("2026-03-02", null),
        row("2026-03-04", -2.1),
      ],
      2,
    );
    expect(out.map((p) => p.date)).toEqual(["2026-03-03", "2026-03-04"]);
    expect(out[1].z).toBe(-2.1);
  });

  it("returns everything when sessions is null", () => {
    const rows = [row("2026-03-01", 1), row("2026-03-02", 2)];
    expect(selectZSeries(rows, null)).toHaveLength(2);
  });

  it("tolerates null input", () => {
    expect(selectZSeries(null, 21)).toEqual([]);
  });
});

describe("pathFromPointsSmooth", () => {
  /** Pull every coordinate pair out of an SVG path's M/C commands. */
  function ys(d: string): number[] {
    return Array.from(d.matchAll(/[-\d.]+,([-\d.]+)/g)).map((m) =>
      Number(m[1]),
    );
  }

  it("never overshoots a spike — the reason this is not Catmull-Rom", () => {
    // Screen coords: y=100 is the zero line, y=0 is the top of the spike.
    // A Catmull-Rom spline dips BELOW the baseline (y > 100) on both flanks,
    // drawing a negative excursion that is not in the data.
    const pts: Point[] = [
      [0, 100],
      [10, 100],
      [20, 0],
      [30, 100],
      [40, 100],
    ];
    const all = ys(pathFromPointsSmooth(pts));
    expect(Math.max(...all)).toBeLessThanOrEqual(100 + 1e-9);
    expect(Math.min(...all)).toBeGreaterThanOrEqual(0 - 1e-9);
  });

  it("stays within the data range on a monotone series", () => {
    const pts: Point[] = [
      [0, 50],
      [10, 40],
      [20, 30],
      [30, 10],
    ];
    const all = ys(pathFromPointsSmooth(pts));
    expect(Math.min(...all)).toBeGreaterThanOrEqual(10 - 1e-9);
    expect(Math.max(...all)).toBeLessThanOrEqual(50 + 1e-9);
  });

  it("passes exactly through every input point", () => {
    const pts: Point[] = [
      [0, 10],
      [10, 90],
      [20, 20],
      [30, 60],
    ];
    const d = pathFromPointsSmooth(pts);
    for (const [x, yv] of pts) expect(d).toContain(`${x},${yv}`);
  });

  it("falls back to a polyline below three points", () => {
    expect(pathFromPointsSmooth([[0, 0]])).toBe("M0,0");
    expect(
      pathFromPointsSmooth([
        [0, 0],
        [1, 1],
      ]),
    ).toBe("M0,0 L1,1");
  });
});
