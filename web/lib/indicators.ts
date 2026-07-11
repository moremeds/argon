// Pure indicator math for the Technicals price pane. Client-side mirror
// precedent: lib/vwap.ts (anchoredVwap). Computed over the FULL series and
// windowed by the caller — EMA/rolling windows need pre-window history.

export type IndicatorBar = {
  as_of?: string | null;
  open?: number | null;
  close?: number | null;
  volume?: number | null;
};

const fin = (v: number | null | undefined): v is number =>
  v != null && Number.isFinite(v);

/** pandas ewm(span=period, adjust=False): alpha = 2/(period+1), seeded at the
 * first finite value. Null input emits null; state carries across it. */
export function ema(
  values: readonly (number | null | undefined)[],
  period: number,
): (number | null)[] {
  const a = 2 / (period + 1);
  let e: number | null = null;
  return values.map((v) => {
    if (!fin(v)) return null;
    e = e == null ? v : a * v + (1 - a) * e;
    return e;
  });
}

/** pandas rolling(period).mean() with min_periods=period: null until the
 * window is full, and null for any window containing a non-finite value. */
export function sma(
  values: readonly (number | null | undefined)[],
  period: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  let bad = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (fin(v)) sum += v;
    else bad++;
    if (i >= period) {
      const o = values[i - period];
      if (fin(o)) sum -= o;
      else bad--;
    }
    if (i >= period - 1 && bad === 0) out[i] = sum / period;
  }
  return out;
}

/** Rolling POPULATION std (ddof=0) — Bollinger/Pine ta.stdev convention. */
export function rollingStd(
  values: readonly (number | null | undefined)[],
  period: number,
): (number | null)[] {
  const out: (number | null)[] = new Array(values.length).fill(null);
  let sum = 0;
  let sumsq = 0;
  let bad = 0;
  for (let i = 0; i < values.length; i++) {
    const v = values[i];
    if (fin(v)) {
      sum += v;
      sumsq += v * v;
    } else bad++;
    if (i >= period) {
      const o = values[i - period];
      if (fin(o)) {
        sum -= o;
        sumsq -= o * o;
      } else bad--;
    }
    if (i >= period - 1 && bad === 0) {
      const mean = sum / period;
      // clamp tiny negative from float error
      out[i] = Math.sqrt(Math.max(0, sumsq / period - mean * mean));
    }
  }
  return out;
}

/** Bollinger envelope: sma(period) ± mult · rollingStd(period). */
export function bollinger(
  closes: readonly (number | null | undefined)[],
  period = 20,
  mult = 2,
): { upper: (number | null)[]; lower: (number | null)[] } {
  const mid = sma(closes, period);
  const sd = rollingStd(closes, period);
  const upper = mid.map((m, i) => {
    const d = sd[i];
    return m != null && d != null ? m + mult * d : null;
  });
  const lower = mid.map((m, i) => {
    const d = sd[i];
    return m != null && d != null ? m - mult * d : null;
  });
  return { upper, lower };
}

/** MarketSmith prevC coloring: up = close >= previous close; the first bar
 * (or a null prev close) falls back to close >= open; null close → null. */
export function prevCloseUp(
  rows: readonly IndicatorBar[],
): (boolean | null)[] {
  return rows.map((r, i) => {
    if (!fin(r.close)) return null;
    const prev = i > 0 ? rows[i - 1].close : null;
    if (fin(prev)) return r.close >= prev;
    return fin(r.open) ? r.close >= r.open : true;
  });
}

/** True where the bar's volume is the minimum of the trailing `window` bars
 * (inclusive). Parity with pandas rolling(window).min(): the first window-1
 * bars are never flagged, and any null inside the window disqualifies it. */
export function lowestInWindow(
  volumes: readonly (number | null | undefined)[],
  window = 10,
): boolean[] {
  return volumes.map((v, i) => {
    if (i < window - 1 || !fin(v)) return false;
    for (let j = i - window + 1; j <= i; j++) {
      const o = volumes[j];
      if (!fin(o) || o < v) return false;
    }
    return true;
  });
}

/** Volume moving average — MarketSmith daily default 50. */
export function volumeMa(
  volumes: readonly (number | null | undefined)[],
  period = 50,
): (number | null)[] {
  return sma(volumes, period);
}

/** 42431978 → "42.43M" (K/M/B, ≤2 decimals, trailing zeros trimmed). */
export function fmtVolCompact(v: number): string {
  const units: [number, string][] = [
    [1e9, "B"],
    [1e6, "M"],
    [1e3, "K"],
  ];
  for (const [div, u] of units) {
    if (v >= div) {
      return `${parseFloat((v / div).toFixed(2))}${u}`;
    }
  }
  return String(Math.round(v));
}

export type VolMarker = {
  time: string;
  position: "aboveBar" | "belowBar";
  shape: "circle";
  color: string;
  text: string;
  size: number;
};

/** Low-relative-volume tags: volume at least |thresholdPct|% below its MA.
 * Ports the Pine modification (lwVolThreshold, default -25). */
export function lowVolMarkers(
  rows: readonly IndicatorBar[],
  ma: readonly (number | null)[],
  opts: { thresholdPct?: number; color: string },
): VolMarker[] {
  const threshold = opts.thresholdPct ?? -25;
  const out: VolMarker[] = [];
  rows.forEach((r, i) => {
    const m = ma[i];
    if (!fin(r.volume) || !fin(m) || m <= 0 || !r.as_of) return;
    const pct = (r.volume / m - 1) * 100;
    if (pct <= threshold) {
      out.push({
        time: r.as_of,
        position: "belowBar",
        shape: "circle",
        color: opts.color,
        text: `${Math.round(pct)}%`,
        size: 0, // dot suppressed; the text is the label
      });
    }
  });
  return out;
}

/** HVE (highest volume ever) / HV1 (highest in a year) labels, deduped so a
 * labeled bar must also be the max of its ±peakLen neighbors (Pine peakL=9).
 * Text: "HVE 152.53M +1.78%" — compact volume + that bar's price change. */
export function highVolMarkers(
  rows: readonly IndicatorBar[],
  opts: { oneYear?: number; peakLen?: number; color: string },
): VolMarker[] {
  const oneYear = opts.oneYear ?? 252;
  const peakLen = opts.peakLen ?? 9;
  const vols = rows.map((r) => r.volume);
  const out: VolMarker[] = [];
  let runningMax = -Infinity;
  rows.forEach((r, i) => {
    const v = vols[i];
    if (!fin(v) || !r.as_of) {
      return;
    }
    const isHve = v > runningMax;
    runningMax = Math.max(runningMax, v);
    // highest of the trailing year (inclusive), only meaningful when not HVE
    let isHv1 = false;
    if (!isHve) {
      isHv1 = true;
      for (let j = Math.max(0, i - oneYear + 1); j < i; j++) {
        const o = vols[j];
        if (fin(o) && o > v) {
          isHv1 = false;
          break;
        }
      }
    }
    if (!isHve && !isHv1) return;
    // peak dedup: must be the max of ±peakLen neighbors
    for (
      let j = Math.max(0, i - peakLen);
      j <= Math.min(rows.length - 1, i + peakLen);
      j++
    ) {
      const o = vols[j];
      if (j !== i && fin(o) && o > v) return;
    }
    const prev = i > 0 ? rows[i - 1].close : null;
    const base = fin(prev) ? prev : fin(r.open) ? r.open : null;
    const chg =
      fin(r.close) && fin(base) && base !== 0
        ? ` ${r.close >= base ? "+" : ""}${(((r.close as number) / (base as number) - 1) * 100).toFixed(2)}%`
        : "";
    out.push({
      time: r.as_of,
      position: "aboveBar",
      shape: "circle",
      color: opts.color,
      text: `${isHve ? "HVE" : "HV1"} ${fmtVolCompact(v)}${chg}`,
      size: 0,
    });
  });
  return out;
}
