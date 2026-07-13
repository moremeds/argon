import { describe, expect, it } from "vitest";

import {
  computeChanlun,
  findFractals,
  mergeInclusions,
  type ChanlunBar,
} from "@/lib/chanlun";
import { AAPL_DAILY_2026H1 } from "../unit/fixtures/aaplDaily2026H1";

const bars: ChanlunBar[] = AAPL_DAILY_2026H1.map((b) => ({
  time: b.as_of,
  high: b.high,
  low: b.low,
  close: b.close,
}));

describe("mergeInclusions", () => {
  const m = mergeInclusions(bars);

  it("leaves no residual inclusion between consecutive merged candles", () => {
    for (let i = 1; i < m.length; i++) {
      const a = m[i - 1];
      const b = m[i];
      const inc =
        (a.high >= b.high && a.low <= b.low) ||
        (b.high >= a.high && b.low <= a.low);
      expect(inc, `merged candles ${i - 1}/${i} still include`).toBe(false);
    }
  });

  it("keeps extreme indices pointing at bars that carry the extreme", () => {
    for (const k of m) {
      expect(bars[k.hiIdx].high).toBe(k.high);
      expect(bars[k.loIdx].low).toBe(k.low);
    }
  });
});

describe("findFractals", () => {
  it("every fractal dominates both neighbors on high AND low", () => {
    const m = mergeInclusions(bars);
    for (const f of findFractals(m)) {
      const [a, b, c] = [m[f.mIdx - 1], m[f.mIdx], m[f.mIdx + 1]];
      if (f.kind === "top") {
        expect(b.high).toBeGreaterThan(Math.max(a.high, c.high));
        expect(b.low).toBeGreaterThan(Math.max(a.low, c.low));
      } else {
        expect(b.low).toBeLessThan(Math.min(a.low, c.low));
        expect(b.high).toBeLessThan(Math.min(a.high, c.high));
      }
    }
  });
});

describe("computeChanlun on real AAPL 2026H1 daily bars", () => {
  const r = computeChanlun(bars);

  it("finds a non-trivial stroke structure in 130 sessions", () => {
    expect(r.vertices.length).toBeGreaterThanOrEqual(5);
  });

  it("vertices alternate top/bottom with strictly increasing times", () => {
    for (let i = 1; i < r.vertices.length; i++) {
      expect(r.vertices[i].kind).not.toBe(r.vertices[i - 1].kind);
      expect(
        r.vertices[i].time.localeCompare(r.vertices[i - 1].time),
      ).toBeGreaterThan(0);
    }
  });

  it("every up-stroke rises and every down-stroke falls", () => {
    for (let i = 1; i < r.vertices.length; i++) {
      const [a, b] = [r.vertices[i - 1], r.vertices[i]];
      if (b.kind === "top") expect(b.price).toBeGreaterThan(a.price);
      else expect(b.price).toBeLessThan(a.price);
    }
  });

  it("confirmed flags form a prefix (provisional only at the tail)", () => {
    const firstProv = r.vertices.findIndex((v) => !v.confirmed);
    expect(firstProv).toBeGreaterThan(0);
    for (let i = firstProv; i < r.vertices.length; i++) {
      expect(r.vertices[i].confirmed).toBe(false);
    }
  });

  it("zhongshus have zg > zd and start < end, within the series range", () => {
    expect(r.zhongshus.length).toBeGreaterThanOrEqual(1);
    for (const z of r.zhongshus) {
      expect(z.zg).toBeGreaterThan(z.zd);
      expect(z.start.localeCompare(z.end)).toBeLessThan(0);
      expect(
        z.start >= bars[0].time && z.end <= bars[bars.length - 1].time,
      ).toBe(true);
    }
  });

  it("buy/sell points sit on stroke vertices with matching side", () => {
    const byTime = new Map(r.vertices.map((v) => [v.time, v]));
    for (const p of r.points) {
      const v = byTime.get(p.time);
      expect(v, `point ${p.kind}@${p.time} not on a vertex`).toBeDefined();
      expect(p.price).toBe(v!.price);
      // buys mark bottoms, sells mark tops
      expect(v!.kind).toBe(p.kind.endsWith("B") ? "bottom" : "top");
    }
  });

  it("is deterministic", () => {
    expect(computeChanlun(bars)).toEqual(r);
  });

  it("returns empty structures for a too-short series", () => {
    expect(computeChanlun(bars.slice(0, 5))).toEqual({
      vertices: [],
      zhongshus: [],
      points: [],
    });
  });
});
