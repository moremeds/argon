import { describe, expect, it } from "vitest";

import {
  computeChanlun,
  computeChanlunFull,
  mergeOverlappingZhongshus,
  type ChanlunBar,
  type Zhongshu,
} from "@/lib/chanlun";
import { AAPL_DAILY_2Y } from "../unit/fixtures/aaplDaily2y";

const bars2y: ChanlunBar[] = AAPL_DAILY_2Y.map((b) => ({
  time: b.as_of,
  high: b.high,
  low: b.low,
  close: b.close,
}));

describe("computeChanlun v1 output identity", () => {
  it("is byte-stable across the v2 refactor (never run vitest -u)", () => {
    expect(computeChanlun(bars2y)).toMatchSnapshot();
  });
});

describe("computeChanlunFull — segment level", () => {
  const full = computeChanlunFull(bars2y);

  it("carries the v1 fields unchanged", () => {
    const v1 = computeChanlun(bars2y);
    expect(full.vertices).toEqual(v1.vertices);
    // full.points may add resonant flags (Task 6) and full.zhongshus may be
    // merged (Task 5); vertices are the anchor that must never move.
  });

  it("segment vertices sit on stroke vertices", () => {
    const byTime = new Map(full.vertices.map((v) => [v.time, v.price]));
    for (const s of full.segVertices) {
      expect(byTime.get(s.time)).toBe(s.price);
    }
  });

  it("段级中枢 are well-formed and time-ordered", () => {
    for (const z of full.segZhongshus) {
      expect(z.zg).toBeGreaterThan(z.zd);
      expect(z.start.localeCompare(z.end)).toBeLessThan(0);
    }
    for (let i = 1; i < full.segZhongshus.length; i++) {
      expect(full.segZhongshus[i].start >= full.segZhongshus[i - 1].start).toBe(
        true,
      );
    }
  });

  it("段级买卖点 sit on segment vertices with matching side", () => {
    const byTime = new Map(full.segVertices.map((v) => [v.time, v]));
    for (const p of full.segPoints) {
      const v = byTime.get(p.time);
      expect(v, `seg point ${p.kind}@${p.time}`).toBeDefined();
      expect(v!.kind).toBe(p.kind.endsWith("B") ? "bottom" : "top");
    }
  });

  it("is deterministic", () => {
    expect(computeChanlunFull(bars2y)).toEqual(full);
  });
});

describe("mergeOverlappingZhongshus", () => {
  // Abstract zone geometry (not market data).
  const z = (start: string, end: string, zd: number, zg: number): Zhongshu => ({
    start,
    end,
    zd,
    zg,
    confirmed: true,
  });

  it("merges consecutive price-overlapping zones into a level-2 envelope", () => {
    const out = mergeOverlappingZhongshus([
      z("2020-01-01", "2020-01-10", 10, 20),
      z("2020-01-11", "2020-01-20", 15, 25),
      z("2020-02-01", "2020-02-10", 40, 50),
    ]);
    expect(out).toHaveLength(2);
    expect(out[0]).toMatchObject({
      start: "2020-01-01",
      end: "2020-01-20",
      zd: 10,
      zg: 25,
      level: 2,
    });
    expect(out[1].level).toBe(1);
  });

  it("merging is transitive across 3 overlapping zones", () => {
    const out = mergeOverlappingZhongshus([
      z("2020-01-01", "2020-01-10", 10, 20),
      z("2020-01-11", "2020-01-20", 15, 25),
      z("2020-01-21", "2020-01-30", 22, 30),
    ]);
    expect(out).toHaveLength(1);
    expect(out[0]).toMatchObject({ zd: 10, zg: 30, level: 2 });
  });

  it("touching-but-not-overlapping zones do not merge", () => {
    const out = mergeOverlappingZhongshus([
      z("2020-01-01", "2020-01-10", 10, 20),
      z("2020-01-11", "2020-01-20", 20, 30), // shares only the edge
    ]);
    expect(out).toHaveLength(2);
  });

  it("computeChanlunFull zhongshus contain no surviving overlap", () => {
    const zs = computeChanlunFull(bars2y).zhongshus;
    for (let i = 1; i < zs.length; i++) {
      const overlap =
        Math.max(zs[i - 1].zd, zs[i].zd) < Math.min(zs[i - 1].zg, zs[i].zg);
      expect(overlap, `zones ${i - 1}/${i} still overlap`).toBe(false);
    }
  });
});
