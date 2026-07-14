import { describe, expect, it } from "vitest";

import {
  buildLegs,
  buildPivots,
  computeChanlun,
  computeChanlunFull,
  markDivergences,
  markPoints,
  markResonance,
  mergeOverlappingZhongshus,
  resampleWeekly,
  type BuySellPoint,
  type ChanlunBar,
  type ChanlunResult,
  type Leg,
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

describe("computeChanlun output identity", () => {
  // Sanctioned re-baselines only — never a routine `vitest -u`. History:
  // (1) 3B/3S side fix (points-only delta, Task 4); (2) exit-leg semantics
  // fix + divergences field (points/divergences-only delta; vertices and
  // zhongshus byte-identical, verified by diff).
  it("is byte-stable (never run vitest -u)", () => {
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

describe("markPoints / markDivergences — realistic-geometry oracles", () => {
  // Abstract geometric fixtures (not market data) — vertex sequences hand
  // constructed to feed buildLegs/buildPivots directly, bypassing fractal
  // derivation. Unlike the retired d6992c8 oracles, these satisfy the
  // invariant real fractal chains always have (each top above its adjacent
  // bottoms) — the old fixtures put a "bottom" above a "top", validating
  // markPoints against inputs the real pipeline can never produce, which
  // hid the fact that buildPivots' exit leg is ALWAYS the counter-direction
  // pullback (zero BSPs on real data).
  const v = (i: number, price: number, kind: "top" | "bottom"): VertexPt => ({
    time: `2020-01-${String(i + 1).padStart(2, "0")}`,
    price,
    kind,
    rawIdx: i,
    confirmed: true,
  });
  const alternating = (
    prices: number[],
    firstKind: "top" | "bottom",
  ): VertexPt[] =>
    prices.map((p, i) =>
      v(i, p, i % 2 === 0 ? firstKind : firstKind === "top" ? "bottom" : "top"),
    );
  // Realism lock: every top strictly above both neighbors (and mirror) —
  // the invariant fractal-derived vertex chains always satisfy.
  const realistic = (pts: VertexPt[]): boolean =>
    pts.every((p, i) => {
      const n = pts[i + 1];
      return !n || (p.kind === "top" ? p.price > n.price : p.price < n.price);
    });
  const flatArea = () => 1;

  it("3B fires on the exit leg's end vertex (the pullback low above zg)", () => {
    // Trio L0-L2 forms zone [105, 148]; L3/L4 still touch it; the breakout
    // leg L4 (112->200) STRADDLES the zone, so the first leg fully outside
    // is L5 (200->160), the down pullback holding above zg -> 3B at v6.
    const pts = alternating([100, 150, 105, 148, 112, 200, 160, 210], "bottom");
    expect(realistic(pts)).toBe(true);
    const legs = buildLegs(pts);
    const pivots = buildPivots(legs);
    expect(pivots).toEqual([
      { firstLeg: 0, lastLeg: 4, exitLeg: 5, exitUp: true, zg: 148, zd: 105 },
    ]);
    const points = markPoints(pts, legs, pivots, flatArea);
    expect(points).toEqual([
      { time: "2020-01-07", price: 160, kind: "3B", confirmed: true },
    ]);
    expect(pts[6].kind).toBe("bottom");
  });

  it("3S fires on the exit leg's end vertex (the pullback high below zd)", () => {
    const pts = alternating([210, 160, 205, 162, 198, 110, 148, 100], "top");
    expect(realistic(pts)).toBe(true);
    const legs = buildLegs(pts);
    const pivots = buildPivots(legs);
    expect(pivots).toEqual([
      { firstLeg: 0, lastLeg: 4, exitLeg: 5, exitUp: false, zg: 205, zd: 162 },
    ]);
    const points = markPoints(pts, legs, pivots, flatArea);
    expect(points).toEqual([
      { time: "2020-01-07", price: 148, kind: "3S", confirmed: true },
    ]);
    expect(pts[6].kind).toBe("top");
  });

  it("1B/2B fire on a two-pivot downtrend with MACD-area 背驰", () => {
    // Two non-overlapping pivots A [182, 200] and B [145, 168] (B.zg <
    // A.zd). Breakout legs (the leg BEFORE each counter-direction exit
    // leg): L4 (198->140) leaves A, L8 (168->120) leaves B on a new low.
    // legArea makes L8 weaker than L4 (1 vs 10) -> 趋势背驰 -> 1B at v9.
    // The first retest v11 (125) holds above the 1B low (120) -> 2B.
    const pts = alternating(
      [210, 180, 200, 182, 198, 140, 170, 145, 168, 120, 138, 125],
      "top",
    );
    expect(realistic(pts)).toBe(true);
    const legs = buildLegs(pts);
    const pivots = buildPivots(legs);
    expect(pivots).toEqual([
      { firstLeg: 0, lastLeg: 4, exitLeg: 5, exitUp: false, zg: 200, zd: 182 },
      { firstLeg: 5, lastLeg: 8, exitLeg: 9, exitUp: false, zg: 168, zd: 145 },
    ]);
    const legArea = (l: Leg) => (l.a === 8 ? 1 : 10);
    const points = markPoints(pts, legs, pivots, legArea);
    expect(points).toEqual([
      { time: "2020-01-07", price: 170, kind: "3S", confirmed: true },
      { time: "2020-01-10", price: 120, kind: "1B", confirmed: true },
      { time: "2020-01-11", price: 138, kind: "3S", confirmed: true },
      { time: "2020-01-12", price: 125, kind: "2B", confirmed: true },
    ]);
  });

  it("底背离 marks the weaker new low; flat MACD area marks nothing", () => {
    const pts = alternating(
      [210, 180, 200, 182, 198, 140, 170, 145, 168, 120, 138, 125],
      "top",
    );
    const legs = buildLegs(pts);
    // L8 (168->120) makes a lower low than L6 (170->145) on area 1 vs 10.
    const legArea = (l: Leg) => (l.a === 8 ? 1 : 10);
    expect(markDivergences(pts, legs, legArea)).toEqual([
      { time: "2020-01-10", price: 120, kind: "bottom", confirmed: true },
    ]);
    // Equal leg areas -> ratio 1 >= 0.9 -> no divergence anywhere.
    expect(markDivergences(pts, legs, flatArea)).toEqual([]);
  });

  it("顶背离 marks the weaker new high", () => {
    const pts = alternating([100, 150, 105, 148, 112, 200, 160, 210], "bottom");
    const legs = buildLegs(pts);
    // L4 (112->200) tops L2's high (148) on area 1 vs L2's 10.
    const legArea = (l: Leg) => (l.a === 4 ? 1 : 10);
    expect(markDivergences(pts, legs, legArea)).toEqual([
      { time: "2020-01-06", price: 200, kind: "top", confirmed: true },
    ]);
  });
});

describe("real-data non-vacuity — the frozen AAPL 2y fixture", () => {
  // Guards against the zero-BSP regression class: gates so strict (or leg
  // identities so wrong) that real data never produces a single mark. Exact
  // values are locked by the snapshot; these document that the pipeline is
  // live at all.
  const r = computeChanlun(bars2y);
  it("produces at least one buy/sell point", () => {
    expect(r.points.length).toBeGreaterThan(0);
  });
  it("produces at least one divergence mark", () => {
    expect(r.divergences.length).toBeGreaterThan(0);
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
    divergences: [],
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
