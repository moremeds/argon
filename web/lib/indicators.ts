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
