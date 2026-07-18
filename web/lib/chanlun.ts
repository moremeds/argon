// Chanlun (缠论) structural decomposition — pure client-side geometry over
// daily OHLC, same precedent as the EMA/Bollinger overlay (lib/indicators.ts).
// Chain: 包含处理 (inclusion merge) → 分型 (fractals) → 笔 (strokes, 新笔-style
// rule) → 中枢 on 笔 (pivot zones) → 三类买卖点 gated by MACD-area 背驰.
// 线段 (segments) deliberately omitted — the feature-sequence gap rules need
// future strokes to confirm and are where repaint ambiguity concentrates.
// Design + sources: docs/research/2026-07-14-chanlun-tv-view-research.md.
//
// The trailing structures are PROVISIONAL by construction (the last stroke
// endpoint can still move, the forming counter-leg tracks the running
// extreme) — consumers must render them dashed/"?" and never alert off them.
import { ema } from "@/lib/indicators";
import { buildSegments, type SegVertex } from "@/lib/chanlunSeg";

export type ChanlunBar = {
  time: string; // 'yyyy-mm-dd'
  high: number;
  low: number;
  close: number;
};

export type MergedK = {
  high: number;
  low: number;
  hiIdx: number; // raw-bar index carrying the merged high
  loIdx: number; // raw-bar index carrying the merged low
};

export type Fractal = {
  kind: "top" | "bottom";
  mIdx: number; // index into the merged-candle array
  rawIdx: number; // raw-bar index of the extreme (marker/vertex placement)
  price: number; // high for top, low for bottom
};

export type BiVertex = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean;
};

export type Zhongshu = {
  start: string;
  end: string;
  zg: number; // upper edge = min(high) of the three forming strokes
  zd: number; // lower edge = max(low)
  confirmed: boolean; // false while the trailing pivot is still extending
  level?: 1 | 2;
};

export type BspKind = "1B" | "2B" | "3B" | "1S" | "2S" | "3S";

export type BuySellPoint = {
  time: string;
  price: number;
  kind: BspKind;
  confirmed: boolean;
  resonant?: boolean;
};

/** 顶背离 (kind "top") / 底背离 (kind "bottom") — a 笔 pushing to a new
 * extreme past the previous same-direction 笔 on weaker MACD area. */
export type DivergenceMark = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  confirmed: boolean;
};

export type ChanlunResult = {
  vertices: BiVertex[];
  zhongshus: Zhongshu[];
  points: BuySellPoint[];
  divergences: DivergenceMark[];
};

// 新笔-style stroke rule: fractal midpoints ≥4 merged candles apart, so the
// two 3-candle fractal windows share no candle and keep ≥1 independent candle
// between them. ponytail: code constant, not a user setting — expose the
// old/new/4K variants only if chart parity with a reference product matters.
const MIN_VERTEX_GAP = 4;
// chan.py default: leg-2 must be ≤90% of leg-1's MACD area to flag 背驰.
const DIVERGENCE_RATE = 0.9;

/** 包含处理 — greedy direction-dependent inclusion merge. Up-merge keeps
 * max(high)/max(low), down-merge min(low)/min(high); the merged candle is
 * re-tested against each next bar. Direction seeds "up" until the first
 * non-inclusive pair sets it (first bars are warmup; the choice washes out). */
export function mergeInclusions(bars: readonly ChanlunBar[]): MergedK[] {
  const m: MergedK[] = [];
  let dir: 1 | -1 = 1;
  bars.forEach((b, i) => {
    const last = m[m.length - 1];
    if (!last) {
      m.push({ high: b.high, low: b.low, hiIdx: i, loIdx: i });
      return;
    }
    const inc =
      (last.high >= b.high && last.low <= b.low) ||
      (b.high >= last.high && b.low <= last.low);
    if (!inc) {
      dir = b.high > last.high ? 1 : -1;
      m.push({ high: b.high, low: b.low, hiIdx: i, loIdx: i });
      return;
    }
    if (dir === 1) {
      if (b.high >= last.high) {
        last.high = b.high;
        last.hiIdx = i;
      }
      if (b.low > last.low) {
        last.low = b.low;
        last.loIdx = i;
      }
    } else {
      if (b.low <= last.low) {
        last.low = b.low;
        last.loIdx = i;
      }
      if (b.high < last.high) {
        last.high = b.high;
        last.hiIdx = i;
      }
    }
  });
  return m;
}

/** 分型 — strict fractals on merged candles: a top's middle candle has both
 * the highest high AND the highest low of its 3-candle window (mirror for
 * bottoms). Raw list; alternation is enforced by the stroke builder. */
export function findFractals(m: readonly MergedK[]): Fractal[] {
  const out: Fractal[] = [];
  for (let i = 1; i < m.length - 1; i++) {
    const [a, b, c] = [m[i - 1], m[i], m[i + 1]];
    if (b.high > a.high && b.high > c.high && b.low > a.low && b.low > c.low) {
      out.push({ kind: "top", mIdx: i, rawIdx: b.hiIdx, price: b.high });
    } else if (
      b.low < a.low &&
      b.low < c.low &&
      b.high < a.high &&
      b.high < c.high
    ) {
      out.push({ kind: "bottom", mIdx: i, rawIdx: b.loIdx, price: b.low });
    }
  }
  return out;
}

/** 笔 endpoints — alternate fractals under the 新笔-style rule. Same-kind
 * fractals keep the more extreme (中继分型 dropped); an opposite fractal
 * appends only when far enough AND on the right side of the last endpoint. */
function buildEndpoints(fractals: readonly Fractal[]): Fractal[] {
  const eps: Fractal[] = [];
  for (const f of fractals) {
    const last = eps[eps.length - 1];
    if (!last) {
      eps.push(f);
      continue;
    }
    if (f.kind === last.kind) {
      const better =
        f.kind === "top" ? f.price >= last.price : f.price <= last.price;
      if (better) eps[eps.length - 1] = f;
      continue;
    }
    const validGap = f.mIdx - last.mIdx >= MIN_VERTEX_GAP;
    const validPrice =
      f.kind === "top" ? f.price > last.price : f.price < last.price;
    if (validGap && validPrice) eps.push(f);
    // else: too close / wrong side — ignored (a later, better fractal wins)
  }
  return eps;
}

// MACD(12,26,9) histogram over closes — the 背驰 momentum proxy. ema() seeds
// at the first value, so every index is finite for finite input.
export function macdHist(closes: readonly number[]): number[] {
  const e12 = ema(closes, 12);
  const e26 = ema(closes, 26);
  const dif = closes.map((_, i) => (e12[i] as number) - (e26[i] as number));
  const dea = ema(dif, 9);
  return dif.map((v, i) => v - (dea[i] as number));
}

export type VertexPt = {
  time: string;
  price: number;
  kind: "top" | "bottom";
  rawIdx: number; // raw-bar index of the vertex extreme (MACD-area bounds)
  confirmed: boolean;
};

export type Leg = {
  hi: number;
  lo: number;
  up: boolean;
  a: number; // start vertex index
  b: number; // end vertex index
  rawA: number;
  rawB: number;
};

export type Pivot = {
  firstLeg: number;
  lastLeg: number; // last leg still inside [zd, zg]
  exitLeg: number | null; // first leg fully outside (null while extending)
  exitUp: boolean;
  zg: number;
  zd: number;
};

export function buildLegs(pts: readonly VertexPt[]): Leg[] {
  const legs: Leg[] = [];
  for (let i = 0; i + 1 < pts.length; i++) {
    legs.push({
      hi: Math.max(pts[i].price, pts[i + 1].price),
      lo: Math.min(pts[i].price, pts[i + 1].price),
      up: pts[i + 1].kind === "top",
      a: i,
      b: i + 1,
      rawA: pts[i].rawIdx,
      rawB: pts[i + 1].rawIdx,
    });
  }
  return legs;
}

// 中枢 — overlap of 3 consecutive strokes: [zd, zg] = [max(lo), min(hi)];
// extends while later strokes still touch the zone, ends at the first
// stroke fully outside. The trailing zone (never exited) stays unconfirmed.
export function buildPivots(legs: readonly Leg[]): Pivot[] {
  const pivots: Pivot[] = [];
  let i = 0;
  while (i <= legs.length - 3) {
    const trio = legs.slice(i, i + 3);
    const zd = Math.max(...trio.map((l) => l.lo));
    const zg = Math.min(...trio.map((l) => l.hi));
    if (zg <= zd) {
      i++;
      continue;
    }
    let lastLeg = i + 2;
    let exitLeg: number | null = null;
    let exitUp = false;
    for (let j = i + 3; j < legs.length; j++) {
      if (legs[j].lo > zg || legs[j].hi < zd) {
        exitLeg = j;
        exitUp = legs[j].lo > zg;
        break;
      }
      lastLeg = j;
    }
    pivots.push({ firstLeg: i, lastLeg, exitLeg, exitUp, zg, zd });
    i = exitLeg ?? legs.length; // the exit leg can seed the next structure
  }
  return pivots;
}

export function pivotsToZhongshus(
  pivots: readonly Pivot[],
  legs: readonly Leg[],
  pts: readonly VertexPt[],
): Zhongshu[] {
  return pivots.map((p) => ({
    start: pts[legs[p.firstLeg].a].time,
    end: pts[legs[p.lastLeg].b].time,
    zg: p.zg,
    zd: p.zd,
    confirmed: p.exitLeg != null,
  }));
}

/** 中枢升级 (pragmatic): consecutive same-level zones whose [zd, zg] ranges
 * overlap merge into one level-2 zone spanning both in time, with the price
 * ENVELOPE [min(zd), max(zg)]. Documented deviation — textbook 九段升级
 * recursion is out of scope (spec §1.3). Transitive by construction. */
export function mergeOverlappingZhongshus(zs: readonly Zhongshu[]): Zhongshu[] {
  const out: Zhongshu[] = [];
  for (const z of zs) {
    const last = out[out.length - 1];
    if (last && Math.max(last.zd, z.zd) < Math.min(last.zg, z.zg)) {
      last.zg = Math.max(last.zg, z.zg);
      last.zd = Math.min(last.zd, z.zd);
      last.end = z.end;
      last.confirmed = last.confirmed && z.confirmed;
      last.level = 2;
    } else {
      out.push({ ...z, level: z.level ?? 1 });
    }
  }
  return out;
}

export function markPoints(
  pts: readonly VertexPt[],
  legs: readonly Leg[],
  pivots: readonly Pivot[],
  legArea: (l: Leg) => number,
): BuySellPoint[] {
  const points: BuySellPoint[] = [];
  const mark = (kind: BspKind, vIdx: number) => {
    const v = pts[vIdx];
    points.push({ time: v.time, price: v.price, kind, confirmed: v.confirmed });
  };
  pivots.forEach((p, k) => {
    // 3B/3S: the exit leg IS the pullback. buildPivots' "first leg fully
    // outside [zd, zg]" is structurally always the counter-direction leg:
    // a trend-direction leg fully above zg would need its start (a bottom
    // vertex) above zg, which would make the PREVIOUS leg fully outside
    // first. So the exit leg leaves the zone and fails to re-enter — its
    // end vertex is the third-class point (its lo > zg / hi < zd already
    // holds by the exit condition). The direction guard keeps a buy off a
    // top vertex for degenerate inputs.
    if (p.exitLeg != null) {
      const exitL = legs[p.exitLeg];
      if (p.exitUp && !exitL.up) mark("3B", exitL.b);
      if (!p.exitUp && exitL.up) mark("3S", exitL.b);
    }
    // 1B/1S: trend (two non-overlapping pivots) whose final BREAKOUT leg —
    // the trend-direction leg just before the counter-direction exit leg —
    // makes a new extreme on weaker MACD area than the previous pivot's
    // breakout leg (趋势背驰).
    const prev = pivots[k - 1];
    if (!prev || prev.exitLeg == null || p.exitLeg == null) return;
    const connect = legs[prev.exitLeg - 1];
    const exit = legs[p.exitLeg - 1];
    const rising = p.zd > prev.zg && connect.up && exit.up;
    const falling = p.zg < prev.zd && !connect.up && !exit.up;
    const newExtreme = rising
      ? pts[exit.b].price > pts[connect.b].price
      : pts[exit.b].price < pts[connect.b].price;
    if (
      (rising || falling) &&
      newExtreme &&
      legArea(exit) < DIVERGENCE_RATE * legArea(connect)
    ) {
      const first = rising ? ("1S" as const) : ("1B" as const);
      mark(first, exit.b);
      // 2B/2S: the first retest after the reversal leg holds the 1st-class
      // extreme (no new low after 1B / no new high after 1S).
      const retest = pts[exit.b + 2];
      if (retest && retest.kind === pts[exit.b].kind) {
        if (first === "1B" && retest.price > pts[exit.b].price) {
          mark("2B", exit.b + 2);
        }
        if (first === "1S" && retest.price < pts[exit.b].price) {
          mark("2S", exit.b + 2);
        }
      }
    }
  });
  points.sort((a, b) => a.time.localeCompare(b.time));
  return points;
}

/** 顶背离/底背离 on 笔: legs i and i+2 are always same-direction (directions
 * alternate); flag the later one when it pushes past the earlier one's
 * extreme on weaker MACD area. Chart annotation only — 买卖点 gating uses
 * the pivot-anchored 趋势背驰 in markPoints. */
export function markDivergences(
  pts: readonly VertexPt[],
  legs: readonly Leg[],
  legArea: (l: Leg) => number,
): DivergenceMark[] {
  const out: DivergenceMark[] = [];
  for (let i = 0; i + 2 < legs.length; i++) {
    const a = legs[i];
    const b = legs[i + 2];
    const extended = b.up
      ? pts[b.b].price > pts[a.b].price
      : pts[b.b].price < pts[a.b].price;
    if (extended && legArea(b) < DIVERGENCE_RATE * legArea(a)) {
      const v = pts[b.b];
      out.push({
        time: v.time,
        price: v.price,
        kind: v.kind,
        confirmed: v.confirmed,
      });
    }
  }
  return out;
}

const EMPTY_RESULT: ChanlunResult = {
  vertices: [],
  zhongshus: [],
  points: [],
  divergences: [],
};

export function computeChanlun(bars: readonly ChanlunBar[]): ChanlunResult {
  if (bars.length < 10) return { ...EMPTY_RESULT };
  const m = mergeInclusions(bars);
  const eps = buildEndpoints(findFractals(m));
  if (eps.length === 0) return { ...EMPTY_RESULT };

  // Provisional tail. The last endpoint is replaceable; two live adjustments:
  // (a) if the running same-direction extreme after it already exceeds it,
  // move it there (that replacement WILL happen once the fractal completes);
  // (b) the forming counter-leg runs to the opposite extreme after the (new)
  // last endpoint. Both redraw as bars arrive — by design, never alert-worthy.
  const confirmedCount = eps.length - 1;
  const tail = eps[eps.length - 1];
  let extSame: Fractal | null = null;
  for (let j = tail.mIdx + 1; j < m.length; j++) {
    const beyond =
      tail.kind === "top"
        ? m[j].high > (extSame ?? tail).price
        : m[j].low < (extSame ?? tail).price;
    if (beyond) {
      extSame =
        tail.kind === "top"
          ? { kind: "top", mIdx: j, rawIdx: m[j].hiIdx, price: m[j].high }
          : { kind: "bottom", mIdx: j, rawIdx: m[j].loIdx, price: m[j].low };
    }
  }
  if (extSame) eps[eps.length - 1] = extSame;
  const anchor = eps[eps.length - 1];
  let forming: Fractal | null = null;
  for (let j = anchor.mIdx + 1; j < m.length; j++) {
    const better =
      anchor.kind === "top"
        ? !forming || m[j].low <= forming.price
        : !forming || m[j].high >= forming.price;
    if (better) {
      forming =
        anchor.kind === "top"
          ? { kind: "bottom", mIdx: j, rawIdx: m[j].loIdx, price: m[j].low }
          : { kind: "top", mIdx: j, rawIdx: m[j].hiIdx, price: m[j].high };
    }
  }
  if (forming) eps.push(forming);

  const vertices: BiVertex[] = eps.map((f, i) => ({
    time: bars[f.rawIdx].time,
    price: f.price,
    kind: f.kind,
    confirmed: i < confirmedCount,
  }));

  const pts: VertexPt[] = eps.map((f, i) => ({
    time: bars[f.rawIdx].time,
    price: f.price,
    kind: f.kind,
    rawIdx: f.rawIdx,
    confirmed: i < confirmedCount,
  }));
  const legs = buildLegs(pts);
  const pivots = buildPivots(legs);
  const zhongshus = pivotsToZhongshus(pivots, legs, pts);

  // 买卖点. Leg momentum = Σ|MACD hist| over the leg's raw bars (area proxy).
  const hist = macdHist(bars.map((b) => b.close));
  const legArea = (l: Leg): number => {
    let s = 0;
    for (let r = l.rawA + 1; r <= l.rawB; r++) {
      s += Math.abs(hist[r]);
    }
    return s;
  };
  const points = markPoints(pts, legs, pivots, legArea);
  const divergences = markDivergences(pts, legs, legArea);

  return { vertices, zhongshus, points, divergences };
}

/** Group daily bars into calendar weeks (Monday key): high=max, low=min,
 * close=last, time=last session of the week. */
export function resampleWeekly(bars: readonly ChanlunBar[]): ChanlunBar[] {
  const monday = (t: string): string => {
    const d = new Date(`${t}T00:00:00Z`);
    d.setUTCDate(d.getUTCDate() - ((d.getUTCDay() + 6) % 7));
    return d.toISOString().slice(0, 10);
  };
  const out: ChanlunBar[] = [];
  let key = "";
  for (const b of bars) {
    const k = monday(b.time);
    if (!out.length || k !== key) {
      key = k;
      out.push({ ...b });
      continue;
    }
    const last = out[out.length - 1];
    last.high = Math.max(last.high, b.high);
    last.low = Math.min(last.low, b.low);
    last.close = b.close;
    last.time = b.time;
  }
  return out;
}

/** 区间套: a confirmed daily point resonates when a same-side confirmed
 * weekly point exists with weekly-vertex time ≤ daily time ≤ end of the
 * weekly point's following leg (spec §1.4). */
export function markResonance(
  points: readonly BuySellPoint[],
  weekly: ChanlunResult,
  lastBarTime: string,
): BuySellPoint[] {
  const windows = weekly.points
    .filter((q) => q.confirmed)
    .map((q) => {
      const vi = weekly.vertices.findIndex(
        (v) => v.time === q.time && v.price === q.price,
      );
      const to =
        vi >= 0 && vi + 1 < weekly.vertices.length
          ? weekly.vertices[vi + 1].time
          : lastBarTime;
      return { side: q.kind.endsWith("B") ? "B" : "S", from: q.time, to };
    });
  if (!windows.length) return [...points];
  return points.map((p) => {
    const side = p.kind.endsWith("B") ? "B" : "S";
    const hit =
      p.confirmed &&
      windows.some(
        (w) => w.side === side && p.time >= w.from && p.time <= w.to,
      );
    return hit ? { ...p, resonant: true } : p;
  });
}

/** Simple moving average of `closes`; out[i] = mean of the trailing `window`
 * values, or null for the first window-1 entries. O(n) prefix-sum roll. */
export function sma(
  closes: readonly number[],
  window: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(closes.length).fill(null);
  let run = 0;
  for (let i = 0; i < closes.length; i++) {
    run += closes[i];
    if (i >= window) run -= closes[i - window];
    if (i >= window - 1) out[i] = run / window;
  }
  return out;
}

/** Per divergence: is it trend-aligned? A 底背离 (bottom) is trend-aligned when
 * its bar closes ABOVE the `window`-SMA (dip inside an uptrend); a 顶背离 (top)
 * when it closes BELOW it. Returns true/false, or null when the SMA is not yet
 * defined at that bar (early history) or the time is not found. The trust probe
 * (docs/research/2026-07-18-chanlun-trust-silver) found the trend-aligned subset
 * carries the stronger honest edge. Aligned index-for-index to `divergences`. */
export function divergenceTrend(
  bars: readonly ChanlunBar[],
  divergences: readonly DivergenceMark[],
  window = 200,
): (boolean | null)[] {
  const idxByTime = new Map(bars.map((b, i) => [b.time, i]));
  const ma = sma(
    bars.map((b) => b.close),
    window,
  );
  return divergences.map((d) => {
    const i = idxByTime.get(d.time);
    if (i === undefined) return null;
    const m = ma[i];
    if (m === null) return null;
    return d.kind === "bottom" ? bars[i].close >= m : bars[i].close < m;
  });
}

export type ChanlunFullResult = ChanlunResult & {
  segVertices: SegVertex[];
  segZhongshus: Zhongshu[];
  segPoints: BuySellPoint[];
};

/** v1 result + segment-level structures. 段级 legs reuse the level-generic
 * pivot/BSP core; MACD-area 背驰 sums over the same raw-bar histogram, just
 * across segment spans. */
export function computeChanlunFull(
  bars: readonly ChanlunBar[],
): ChanlunFullResult {
  const daily = computeChanlun(bars);
  const segVertices = buildSegments(daily.vertices);
  const idxByTime = new Map(bars.map((b, i) => [b.time, i]));
  const segPts: VertexPt[] = segVertices.map((v) => ({
    time: v.time,
    price: v.price,
    kind: v.kind,
    rawIdx: idxByTime.get(v.time) ?? 0,
    confirmed: v.confirmed,
  }));
  const hist = macdHist(bars.map((b) => b.close));
  const legArea = (l: Leg): number => {
    let s = 0;
    for (let r = l.rawA + 1; r <= l.rawB; r++) {
      s += Math.abs(hist[r]);
    }
    return s;
  };
  const segLegs = buildLegs(segPts);
  const segPivots = buildPivots(segLegs);
  const weekly = computeChanlun(resampleWeekly(bars));
  const points = markResonance(
    daily.points,
    weekly,
    bars[bars.length - 1]?.time ?? "",
  );
  return {
    ...daily,
    points,
    zhongshus: mergeOverlappingZhongshus(daily.zhongshus),
    segVertices,
    segZhongshus: pivotsToZhongshus(segPivots, segLegs, segPts),
    segPoints: markPoints(segPts, segLegs, segPivots, legArea),
  };
}
