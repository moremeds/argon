import { describe, expect, it } from "vitest";

import {
  buildLegs,
  buildPivots,
  computeChanlun,
  computeChanlunFull,
  markPoints,
  markResonance,
  mergeOverlappingZhongshus,
  resampleWeekly,
  type BuySellPoint,
  type ChanlunBar,
  type ChanlunResult,
  type VertexPt,
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

describe("markPoints — 3B/3S side-correctness oracle", () => {
  // Abstract geometric fixtures (not market data) — 6-vertex sequences hand
  // constructed to feed buildLegs/buildPivots directly, bypassing fractal
  // derivation. Each proves the pull leg must OPPOSE the pivot's exit
  // direction (regression lock for commit d6992c8): "fully outside" alone
  // is not enough, since a counter-direction leg riding above/below the
  // zone can also match, which would put a buy marker on a top vertex.
  const legArea = () => 1; // 3B/3S don't use divergence — constant is fine.

  it("3B fires on the pullback's end vertex, which is a bottom", () => {
    // Trio (v0..v3) forms a pivot [zd=100, zg=150]. Leg v3->v4 exits fully
    // above zg (200,210 both > 150) -> exitUp=true. The pull leg v4->v5
    // opposes that exit (a down leg, 210->160) and stays fully above zg
    // (160 > 150), so it marks 3B at v5 — which must be a bottom vertex.
    const pts: VertexPt[] = [
      {
        time: "2020-01-01",
        price: 100,
        kind: "top",
        rawIdx: 0,
        confirmed: true,
      },
      {
        time: "2020-01-02",
        price: 150,
        kind: "bottom",
        rawIdx: 1,
        confirmed: true,
      },
      {
        time: "2020-01-03",
        price: 90,
        kind: "top",
        rawIdx: 2,
        confirmed: true,
      },
      {
        time: "2020-01-04",
        price: 200,
        kind: "bottom",
        rawIdx: 3,
        confirmed: true,
      },
      {
        time: "2020-01-05",
        price: 210,
        kind: "top",
        rawIdx: 4,
        confirmed: true,
      },
      {
        time: "2020-01-06",
        price: 160,
        kind: "bottom",
        rawIdx: 5,
        confirmed: true,
      },
    ];
    const legs = buildLegs(pts);
    const pivots = buildPivots(legs);
    expect(pivots).toEqual([
      { firstLeg: 0, lastLeg: 2, exitLeg: 3, exitUp: true, zg: 150, zd: 100 },
    ]);
    const points = markPoints(pts, legs, pivots, legArea);
    expect(points).toEqual([
      { time: "2020-01-06", price: 160, kind: "3B", confirmed: true },
    ]);
    expect(pts[5].kind).toBe("bottom");
  });

  it("3S fires on the pullback's end vertex, which is a top", () => {
    // Mirror of the 3B fixture: pivot [zd=160, zg=210]. Leg v3->v4 exits
    // fully below zd (110,100 both < 160) -> exitUp=false. The pull leg
    // v4->v5 opposes that exit (an up leg, 100->150) and stays fully below
    // zd (150 < 160), so it marks 3S at v5 — which must be a top vertex.
    const pts: VertexPt[] = [
      {
        time: "2020-01-01",
        price: 210,
        kind: "bottom",
        rawIdx: 0,
        confirmed: true,
      },
      {
        time: "2020-01-02",
        price: 160,
        kind: "top",
        rawIdx: 1,
        confirmed: true,
      },
      {
        time: "2020-01-03",
        price: 220,
        kind: "bottom",
        rawIdx: 2,
        confirmed: true,
      },
      {
        time: "2020-01-04",
        price: 110,
        kind: "top",
        rawIdx: 3,
        confirmed: true,
      },
      {
        time: "2020-01-05",
        price: 100,
        kind: "bottom",
        rawIdx: 4,
        confirmed: true,
      },
      {
        time: "2020-01-06",
        price: 150,
        kind: "top",
        rawIdx: 5,
        confirmed: true,
      },
    ];
    const legs = buildLegs(pts);
    const pivots = buildPivots(legs);
    expect(pivots).toEqual([
      { firstLeg: 0, lastLeg: 2, exitLeg: 3, exitUp: false, zg: 210, zd: 160 },
    ]);
    const points = markPoints(pts, legs, pivots, legArea);
    expect(points).toEqual([
      { time: "2020-01-06", price: 150, kind: "3S", confirmed: true },
    ]);
    expect(pts[5].kind).toBe("top");
  });
});

describe("markResonance — positive case", () => {
  // Abstract geometric fixtures (not market data).
  const weekly: ChanlunResult = {
    vertices: [
      { time: "2020-03-01", price: 40, kind: "bottom", confirmed: true },
      { time: "2020-03-15", price: 60, kind: "top", confirmed: true },
    ],
    zhongshus: [],
    points: [{ time: "2020-03-01", price: 40, kind: "1B", confirmed: true }],
  };
  const lastBarTime = "2020-04-01";

  // p1: confirmed, in-window ([2020-03-01, 2020-03-15]), same side (B).
  const p1: BuySellPoint = {
    time: "2020-03-10",
    price: 50,
    kind: "1B",
    confirmed: true,
  };
  // p2: unconfirmed but otherwise in-window / same-side — must not resonate.
  const p2: BuySellPoint = {
    time: "2020-03-11",
    price: 52,
    kind: "1B",
    confirmed: false,
  };
  // p3: confirmed, in-window, but wrong side (S, no S window exists) — must
  // not resonate.
  const p3: BuySellPoint = {
    time: "2020-03-12",
    price: 48,
    kind: "1S",
    confirmed: true,
  };

  it("flags the confirmed in-window same-side point and only that one", () => {
    const points = [p1, p2, p3];
    const out = markResonance(points, weekly, lastBarTime);
    expect(out).toEqual([{ ...p1, resonant: true }, p2, p3]);
    // Unconfirmed and wrong-side points never get the flag.
    expect(out[1].resonant).toBeUndefined();
    expect(out[2].resonant).toBeUndefined();
  });

  it("does not mutate the input points", () => {
    const points = [p1, p2, p3];
    markResonance(points, weekly, lastBarTime);
    expect(points[0]).toBe(p1);
    expect(p1.resonant).toBeUndefined();
    expect(p2.resonant).toBeUndefined();
    expect(p3.resonant).toBeUndefined();
  });
});
