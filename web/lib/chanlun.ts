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
};

export type ChanlunResult = {
  vertices: BiVertex[];
  zhongshus: Zhongshu[];
  points: BuySellPoint[];
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
function macdHist(closes: readonly number[]): number[] {
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
    if (p.exitLeg != null) {
      const pull = legs[p.exitLeg + 1];
      if (pull && p.exitUp && pull.lo > p.zg) mark("3B", pull.b);
      if (pull && !p.exitUp && pull.hi < p.zd) mark("3S", pull.b);
    }
    const prev = pivots[k - 1];
    if (!prev || prev.exitLeg == null || p.exitLeg == null) return;
    const connect = legs[prev.exitLeg];
    const exit = legs[p.exitLeg];
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

export function computeChanlun(bars: readonly ChanlunBar[]): ChanlunResult {
  if (bars.length < 10) return { vertices: [], zhongshus: [], points: [] };
  const m = mergeInclusions(bars);
  const eps = buildEndpoints(findFractals(m));
  if (eps.length === 0) return { vertices: [], zhongshus: [], points: [] };

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

  const hist = macdHist(bars.map((b) => b.close));
  const legArea = (l: Leg): number => {
    let s = 0;
    for (let r = l.rawA + 1; r <= l.rawB; r++) {
      s += Math.abs(hist[r]);
    }
    return s;
  };
  const points = markPoints(pts, legs, pivots, legArea);

  return { vertices, zhongshus, points };
}
