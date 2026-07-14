import { describe, expect, it } from "vitest";

import { computeChanlun, type BiVertex, type ChanlunBar } from "@/lib/chanlun";
import { buildSegments, type SegStats, type SegVertex } from "@/lib/chanlunSeg";
import { AAPL_DAILY_2Y } from "../unit/fixtures/aaplDaily2y";

// Abstract algorithm-geometry oracles (NOT market data): alternating stroke
// vertices with relative price levels, hand-traced through the chan.py
// feature-sequence rules (Seg/EigenFX.py). Dates are index placeholders.
function verts(prices: number[], confirmed = true): BiVertex[] {
  return prices.map((p, i) => ({
    time: `2020-01-${String(i + 1).padStart(2, "0")}`,
    price: p,
    kind: i % 2 === (prices[1] > prices[0] ? 1 : 0) ? "top" : "bottom",
    confirmed,
  }));
}

const prices = (out: SegVertex[]) => out.map((v) => v.price);
const confs = (out: SegVertex[]) => out.map((v) => v.confirmed);

describe("buildSegments — chan.py oracle traces", () => {
  it("A: case-1 immediate termination", () => {
    // 0→10→6→12→8→11→4: up segment ends at 12 (V3), no gap.
    const out = buildSegments(verts([0, 10, 6, 12, 8, 11, 4]));
    expect(prices(out)).toEqual([0, 12, 4]);
    expect(confs(out)).toEqual([true, true, false]);
  });

  it("B: case-2 gap confirmed by the next segment's own fractal", () => {
    // 0→10→8→20→15→18→5→9→3→7→4→11: gap top at 20 confirmed; the down
    // segment to 3 (V8) also confirms; tail up to 11 provisional.
    const out = buildSegments(verts([0, 10, 8, 20, 15, 18, 5, 9, 3, 7, 4, 11]));
    expect(prices(out)).toEqual([0, 20, 3, 11]);
    expect(confs(out)).toEqual([true, true, true, false]);
  });

  it("C: case-2 gap unconfirmed at the tail → provisional", () => {
    // Example B truncated before the reverse fractal completes.
    const out = buildSegments(verts([0, 10, 8, 20, 15, 18, 5, 9]));
    expect(out[1]?.price).toBe(20);
    expect(out.every((v) => !v.confirmed)).toBe(true); // whole chain provisional
  });

  it("D: reset() continuation — premature top rejected, true top found", () => {
    // 0→10→6→14→9→18→12→16→4: the 14-top fractal fails (feature seq still
    // rising); detector resets and the segment runs to 18 (case 1).
    const out = buildSegments(verts([0, 10, 6, 14, 9, 18, 12, 16, 4]));
    expect(prices(out)).toEqual([0, 18, 4]);
    expect(confs(out)).toEqual([true, true, false]);
  });

  it("counts termination cases via the stats hook", () => {
    const stats: SegStats = {
      case1: 0,
      case2Confirmed: 0,
      case2Provisional: 0,
    };
    buildSegments(verts([0, 10, 8, 20, 15, 18, 5, 9, 3, 7, 4, 11]), stats);
    expect(stats.case2Confirmed).toBe(1);
  });
});

describe("buildSegments — invariants on real AAPL 2y strokes", () => {
  const bars: ChanlunBar[] = AAPL_DAILY_2Y.map((b) => ({
    time: b.as_of,
    high: b.high,
    low: b.low,
    close: b.close,
  }));
  const vertices = computeChanlun(bars).vertices;
  const segs = buildSegments(vertices);

  it("produces a non-trivial segment structure", () => {
    expect(segs.length).toBeGreaterThanOrEqual(3);
  });

  it("endpoints are stroke vertices (time AND price match)", () => {
    const byTime = new Map(vertices.map((v) => [v.time, v]));
    for (const s of segs) {
      const v = byTime.get(s.time);
      expect(v, `seg vertex ${s.time} not a stroke vertex`).toBeDefined();
      expect(v!.price).toBe(s.price);
      expect(v!.kind).toBe(s.kind);
    }
  });

  it("alternates top/bottom with strictly increasing times", () => {
    // chan.py CSeg.__init__ permits the FIRST segment to start on a
    // mismatched-kind vertex (start_bi.idx == 0 exception) — the series
    // boundary can cut mid-structure, so vertices[0]'s kind may equal the
    // first segment end's kind. Alternation binds from the second pair on.
    for (let i = 1; i < segs.length; i++) {
      if (i >= 2) expect(segs[i].kind).not.toBe(segs[i - 1].kind);
      expect(segs[i].time.localeCompare(segs[i - 1].time)).toBeGreaterThan(0);
    }
  });

  it("every confirmed segment spans ≥3 strokes", () => {
    const idxByTime = new Map(vertices.map((v, i) => [v.time, i]));
    for (let i = 1; i < segs.length; i++) {
      if (!segs[i].confirmed) continue;
      const span =
        (idxByTime.get(segs[i].time) ?? 0) -
        (idxByTime.get(segs[i - 1].time) ?? 0);
      expect(span, `segment ending ${segs[i].time}`).toBeGreaterThanOrEqual(3);
    }
  });

  it("confirmed flags form a prefix", () => {
    const firstProv = segs.findIndex((v) => !v.confirmed);
    if (firstProv !== -1) {
      for (let i = firstProv; i < segs.length; i++) {
        expect(segs[i].confirmed).toBe(false);
      }
    }
  });

  it("is deterministic", () => {
    expect(buildSegments(vertices)).toEqual(segs);
  });

  it("returns empty for degenerate input", () => {
    expect(buildSegments([])).toEqual([]);
    expect(buildSegments(vertices.slice(0, 1))).toEqual([]);
  });
});
