import { describe, expect, it } from "vitest";

import {
  computeChanlun,
  computeChanlunFull,
  mergeOverlappingZhongshus,
  resampleWeekly,
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

describe("resampleWeekly", () => {
  const weekly = resampleWeekly(bars2y);

  it("conserves OHLC per calendar week", () => {
    // Recompute each weekly bar from the daily bars sharing its week and
    // compare — max(high), min(low), last close, last session time.
    const monday = (t: string) => {
      const d = new Date(`${t}T00:00:00Z`);
      d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
      return d.toISOString().slice(0, 10);
    };
    const groups = new Map<string, typeof bars2y>();
    for (const b of bars2y) {
      const k = monday(b.time);
      groups.set(k, [...(groups.get(k) ?? []), b]);
    }
    expect(weekly.length).toBe(groups.size);
    for (const w of weekly) {
      const g = groups.get(monday(w.time))!;
      expect(w.high).toBe(Math.max(...g.map((b) => b.high)));
      expect(w.low).toBe(Math.min(...g.map((b) => b.low)));
      expect(w.close).toBe(g[g.length - 1].close);
      expect(w.time).toBe(g[g.length - 1].time);
    }
  });

  it("week keys strictly increase", () => {
    for (let i = 1; i < weekly.length; i++) {
      expect(weekly[i].time.localeCompare(weekly[i - 1].time)).toBeGreaterThan(
        0,
      );
    }
  });
});

describe("区间套 resonance", () => {
  const full = computeChanlunFull(bars2y);

  it("resonant points are confirmed daily points with a confirmed weekly witness", () => {
    const weekly = computeChanlun(resampleWeekly(bars2y));
    const lastBar = bars2y[bars2y.length - 1].time;
    for (const p of full.points) {
      if (!p.resonant) continue;
      expect(p.confirmed).toBe(true);
      const side = p.kind.endsWith("B") ? "B" : "S";
      const witness = weekly.points.some((q) => {
        if (!q.confirmed || (q.kind.endsWith("B") ? "B" : "S") !== side) {
          return false;
        }
        const vi = weekly.vertices.findIndex(
          (v) => v.time === q.time && v.price === q.price,
        );
        const to =
          vi >= 0 && vi + 1 < weekly.vertices.length
            ? weekly.vertices[vi + 1].time
            : lastBar;
        return p.time >= q.time && p.time <= to;
      });
      expect(witness, `no weekly witness for ${p.kind}@${p.time}`).toBe(true);
    }
  });

  it("non-resonant and provisional points never carry the flag", () => {
    for (const p of full.points) {
      if (!p.confirmed) expect(p.resonant).toBeUndefined();
    }
  });
});
