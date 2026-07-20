/**
 * Volume-profile window study — how should the VP overlay choose its bar window?
 *
 * Reproduce:
 *   cd web && npx tsx ../scripts/research/volume_profile_window_study.mts
 *
 * Imports the SHIPPED compute (web/lib/volumeProfile.ts) so the numbers describe
 * what the chart actually draws, not a re-implementation. Bars come from the
 * apex REST API (real daily OHLCV, cached to the scratchpad after first fetch).
 *
 * Three questions, in the order they matter for the decision:
 *
 *   A. PAN SENSITIVITY — at a FIXED date, how much do the levels move as the
 *      window length changes? This is the "why does it change when I scroll"
 *      complaint measured directly: panning a visible-range profile changes W.
 *
 *   B. TIME CHURN — at a FIXED window length, how much do levels and the
 *      BUY/SELL mark set move as one new bar arrives? This is repaint.
 *
 *   C. EFFICACY — are the levels worth anything? Point-in-time zones only
 *      (bars <= t), forward returns from the touch bar, against a distance- and
 *      direction-matched placebo level. Without the placebo this measures the
 *      market's drift, not the level.
 *
 * All three are needed: A and B alone are minimised by an infinite window, which
 * would be perfectly stable and perfectly useless.
 */
import { writeFileSync, readFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import {
  computeVolumeProfile,
  findSrZones,
  type SrZone,
  type VpBar,
} from "../../web/lib/volumeProfile.ts";

const APEX = "http://100.66.147.98:8322";
const TICKERS = ["SPY", "QQQ", "IWM", "AAPL", "NVDA", "MSFT"];
const CACHE = "/private/tmp/claude-501/-Users-chenxi-projects-argon/2035550c-04d2-4b00-a4d7-8f56c85c7b72/scratchpad/vp_bars.json";
const OUT_JSON = "docs/research/2026-07-20-volume-profile-window-study.json";

const BINS = 60;
const VALUE_PCT = 70;
// Through 5y (1260 sessions) and beyond, to test "longer is always better".
const WINDOWS = [60, 120, 250, 360, 500, 750, 1000, 1260, 2000];
const STRIDE = 5; // subsample evaluation dates; 20y of dailies is plenty
const FWD = 5; // forward horizon (sessions) for the efficacy test
const VOL_MA = 20;

type Bar = VpBar & { time: string };

// ---------------------------------------------------------------- data

async function loadBars(): Promise<Record<string, Bar[]>> {
  if (existsSync(CACHE)) return JSON.parse(readFileSync(CACHE, "utf8"));
  const out: Record<string, Bar[]> = {};
  for (const t of TICKERS) {
    const r = await fetch(`${APEX}/bars/${t}?timeframe=1d&limit=5000`);
    if (!r.ok) throw new Error(`apex ${t}: ${r.status}`);
    const j = (await r.json()) as { bars: Record<string, number | string>[] };
    out[t] = j.bars
      .filter((b) => b.volume != null && b.open != null)
      .map((b) => ({
        time: String(b.time).slice(0, 10),
        open: Number(b.open),
        high: Number(b.high),
        low: Number(b.low),
        close: Number(b.close),
        volume: Number(b.volume),
      }));
    process.stderr.write(`fetched ${t}: ${out[t].length} bars\n`);
  }
  mkdirSync(dirname(CACHE), { recursive: true });
  writeFileSync(CACHE, JSON.stringify(out));
  return out;
}

// ---------------------------------------------------------------- helpers

/** Wilder-free ATR14: plain mean of true range, enough for a scale denominator. */
function atrAt(bars: Bar[], t: number, n = 14): number {
  let sum = 0;
  let k = 0;
  for (let i = Math.max(1, t - n + 1); i <= t; i += 1) {
    const tr = Math.max(
      bars[i].high - bars[i].low,
      Math.abs(bars[i].high - bars[i - 1].close),
      Math.abs(bars[i].low - bars[i - 1].close),
    );
    sum += tr;
    k += 1;
  }
  return k ? sum / k : NaN;
}

function quantile(xs: number[], q: number): number {
  if (xs.length === 0) return NaN;
  const s = [...xs].sort((a, b) => a - b);
  const i = (s.length - 1) * q;
  const lo = Math.floor(i);
  const hi = Math.ceil(i);
  return lo === hi ? s[lo] : s[lo] + (s[hi] - s[lo]) * (i - lo);
}

const mean = (xs: number[]) =>
  xs.length ? xs.reduce((a, b) => a + b, 0) / xs.length : NaN;

/** Profile + zones from bars[a..t] inclusive — strictly point-in-time. */
function levelsAt(bars: Bar[], t: number, w: number) {
  const a = Math.max(0, t - w + 1);
  const slice = bars.slice(a, t + 1);
  const p = computeVolumeProfile(slice, BINS, VALUE_PCT);
  if (!p) return null;
  const zones = findSrZones(p, slice, bars[t].close);
  const sup = zones.filter((z) => z.side === "support").map((z) => z.price);
  const res = zones.filter((z) => z.side === "resistance").map((z) => z.price);
  return {
    poc: p.pocPrice,
    vah: p.bins[p.vahIdx].high,
    val: p.bins[p.valIdx].low,
    nearestSup: sup.length ? Math.max(...sup) : null,
    nearestRes: res.length ? Math.min(...res) : null,
    zones,
  };
}

/**
 * BUY/SELL/touch/reject marks over a trailing span, using ONE pair of levels.
 * Mirrors the rule in TechnicalsPriceChart.tsx (that component is the source of
 * truth); duplicated here rather than imported because the component pulls in
 * React. Encoded as a string set so two recomputes can be diffed.
 */
function markSet(
  bars: Bar[],
  from: number,
  to: number,
  sup: number | null,
  res: number | null,
  volMa: (number | null)[],
): Set<string> {
  const out = new Set<string>();
  for (let i = Math.max(1, from); i <= to; i += 1) {
    const b = bars[i];
    const prev = bars[i - 1].close;
    const ma = volMa[i];
    const volOk = ma != null && b.volume > ma;
    if (res != null && volOk && prev <= res && b.close > res) {
      out.add(`${b.time}:BUY`);
    } else if (sup != null && volOk && prev >= sup && b.close < sup) {
      out.add(`${b.time}:SELL`);
    } else if (sup != null && b.low <= sup && b.close > sup) {
      out.add(`${b.time}:TOUCH`);
    } else if (res != null && b.high >= res && b.close < res) {
      out.add(`${b.time}:REJECT`);
    }
  }
  return out;
}

function volumeMa(bars: Bar[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < bars.length; i += 1) {
    sum += bars[i].volume;
    if (i >= n) sum -= bars[i - n].volume;
    out.push(i >= n - 1 ? sum / n : null);
  }
  return out;
}

// ---------------------------------------------------------------- experiments

/** A. At a fixed date, how far do levels move as W varies over a pan range? */
function panSensitivity(bars: Bar[]) {
  const spreads: number[] = [];
  const supSpreads: number[] = [];
  for (let t = 800; t < bars.length; t += STRIDE * 4) {
    const atr = atrAt(bars, t);
    if (!(atr > 0)) continue;
    const pocs: number[] = [];
    const sups: number[] = [];
    // A plausible scroll range: the user pans between ~150 and ~600 visible bars.
    for (const w of [150, 200, 250, 300, 400, 500, 600]) {
      const L = levelsAt(bars, t, w);
      if (!L) continue;
      pocs.push(L.poc);
      if (L.nearestSup != null) sups.push(L.nearestSup);
    }
    if (pocs.length > 1) spreads.push((Math.max(...pocs) - Math.min(...pocs)) / atr);
    if (sups.length > 1)
      supSpreads.push((Math.max(...sups) - Math.min(...sups)) / atr);
  }
  return {
    pocSpreadAtrMedian: quantile(spreads, 0.5),
    pocSpreadAtrP90: quantile(spreads, 0.9),
    nearestSupSpreadAtrMedian: quantile(supSpreads, 0.5),
    n: spreads.length,
  };
}

/** B. At a fixed W, how much do levels and marks move when one bar arrives? */
function timeChurn(bars: Bar[], w: number, vma: (number | null)[]) {
  const pocMove: number[] = [];
  const markChurn: number[] = [];
  let prev: ReturnType<typeof levelsAt> = null;
  let prevMarks: Set<string> | null = null;
  for (let t = Math.max(w, 800); t < bars.length; t += 1) {
    const atr = atrAt(bars, t);
    const L = levelsAt(bars, t, w);
    if (!L || !(atr > 0)) {
      prev = null;
      prevMarks = null;
      continue;
    }
    // Marks the chart would draw today over the trailing 250 sessions.
    const marks = markSet(
      bars,
      t - 250,
      t,
      L.nearestSup,
      L.nearestRes,
      vma,
    );
    if (prev && prevMarks) {
      pocMove.push(Math.abs(L.poc - prev.poc) / atr);
      // Churn = symmetric difference over union, restricted to marks whose bar
      // exists in both recomputes (so the newest bar's arrival isn't counted).
      const a = new Set([...prevMarks].filter((m) => m.slice(0, 10) < bars[t].time));
      const b = new Set([...marks].filter((m) => m.slice(0, 10) < bars[t].time));
      const uni = new Set([...a, ...b]);
      let diff = 0;
      for (const m of uni) if (!a.has(m) || !b.has(m)) diff += 1;
      markChurn.push(uni.size ? diff / uni.size : 0);
    }
    prev = L;
    prevMarks = marks;
  }
  return {
    pocMoveAtrMedian: quantile(pocMove, 0.5),
    pocMoveAtrP90: quantile(pocMove, 0.9),
    markChurnMean: mean(markChurn),
    markChurnP90: quantile(markChurn, 0.9),
    n: pocMove.length,
  };
}

/**
 * C. Do the zones do anything? Point-in-time zones from bars<=t; find the first
 * touch within the next 20 sessions; measure FWD-session return from the touch
 * close. Placebo = a level at the same signed distance from spot but shifted to
 * a price the profile does NOT call a shelf.
 */
function efficacy(bars: Bar[], w: number) {
  const real: Record<"support" | "resistance", number[]> = {
    support: [],
    resistance: [],
  };
  const placebo: Record<"support" | "resistance", number[]> = {
    support: [],
    resistance: [],
  };

  const firstTouchFwd = (t: number, level: number) => {
    for (let i = t + 1; i <= Math.min(t + 20, bars.length - FWD - 1); i += 1) {
      if (bars[i].low <= level && bars[i].high >= level) {
        return (bars[i + FWD].close - bars[i].close) / bars[i].close;
      }
    }
    return null;
  };

  for (let t = Math.max(w, 800); t < bars.length - FWD - 21; t += STRIDE) {
    const L = levelsAt(bars, t, w);
    if (!L) continue;
    const spot = bars[t].close;
    for (const side of ["support", "resistance"] as const) {
      const lvl = side === "support" ? L.nearestSup : L.nearestRes;
      if (lvl == null) continue;
      const r = firstTouchFwd(t, lvl);
      if (r != null) real[side].push(r);
      // Placebo: same distance, nudged 40% further out — a price the profile
      // did not flag, so any difference is the zone, not the distance.
      const shifted = spot + (lvl - spot) * 1.4;
      const rp = firstTouchFwd(t, shifted);
      if (rp != null) placebo[side].push(rp);
    }
  }
  return {
    supportRealMeanBp: mean(real.support) * 1e4,
    supportPlaceboMeanBp: mean(placebo.support) * 1e4,
    supportN: real.support.length,
    resistanceRealMeanBp: mean(real.resistance) * 1e4,
    resistancePlaceboMeanBp: mean(placebo.resistance) * 1e4,
    resistanceN: real.resistance.length,
  };
}

// ---------------------------------------------------------------- main

const bars = await loadBars();
const results: Record<string, unknown> = {
  meta: {
    generated_for: "volume-profile window choice",
    source: `${APEX}/bars/{ticker}?timeframe=1d&limit=5000`,
    tickers: TICKERS,
    bins: BINS,
    valuePct: VALUE_PCT,
    windows: WINDOWS,
    stride: STRIDE,
    fwdSessions: FWD,
    reproduce:
      "cd web && npx tsx ../scripts/research/volume_profile_window_study.mts",
    note: "Imports the shipped web/lib/volumeProfile.ts. All levels strictly point-in-time (bars <= t).",
  },
};

const perTicker: Record<string, unknown> = {};
for (const tk of TICKERS) {
  const b = bars[tk];
  const vma = volumeMa(b, VOL_MA);
  const entry: Record<string, unknown> = {
    bars: b.length,
    range: [b[0].time, b[b.length - 1].time],
    panSensitivity: panSensitivity(b),
    byWindow: {} as Record<string, unknown>,
  };
  for (const w of WINDOWS) {
    (entry.byWindow as Record<string, unknown>)[String(w)] = {
      churn: timeChurn(b, w, vma),
      efficacy: efficacy(b, w),
    };
  }
  perTicker[tk] = entry;
  process.stderr.write(`done ${tk}\n`);
}
results.perTicker = perTicker;

// Cross-ticker aggregate: median of per-ticker stats, plus a sign-consistency
// count (how many tickers agree) — more honest than a pooled p-value given
// heavy autocorrelation and cross-sectional correlation between these names.
const agg: Record<string, unknown> = {};
for (const w of WINDOWS) {
  const ch = TICKERS.map(
    (t) => (perTicker[t] as any).byWindow[String(w)].churn,
  );
  const ef = TICKERS.map(
    (t) => (perTicker[t] as any).byWindow[String(w)].efficacy,
  );
  const supEdge = ef.map(
    (e: any) => e.supportRealMeanBp - e.supportPlaceboMeanBp,
  );
  const resEdge = ef.map(
    (e: any) => e.resistanceRealMeanBp - e.resistancePlaceboMeanBp,
  );
  agg[String(w)] = {
    pocMoveAtrMedian: quantile(ch.map((c: any) => c.pocMoveAtrMedian), 0.5),
    markChurnMean: mean(ch.map((c: any) => c.markChurnMean)),
    supportEdgeBpMedian: quantile(supEdge, 0.5),
    supportEdgeTickersPositive: supEdge.filter((x) => x > 0).length,
    resistanceEdgeBpMedian: quantile(resEdge, 0.5),
    resistanceEdgeTickersNegative: resEdge.filter((x) => x < 0).length,
    tickers: TICKERS.length,
  };
}
results.aggregate = agg;
results.panSensitivityAggregate = {
  pocSpreadAtrMedian: quantile(
    TICKERS.map((t) => (perTicker[t] as any).panSensitivity.pocSpreadAtrMedian),
    0.5,
  ),
  nearestSupSpreadAtrMedian: quantile(
    TICKERS.map(
      (t) => (perTicker[t] as any).panSensitivity.nearestSupSpreadAtrMedian,
    ),
    0.5,
  ),
};

mkdirSync(dirname(OUT_JSON), { recursive: true });
writeFileSync(OUT_JSON, JSON.stringify(results, null, 2));
console.log(JSON.stringify({ aggregate: agg, pan: results.panSensitivityAggregate }, null, 2));
process.stderr.write(`\nwrote ${OUT_JSON}\n`);
