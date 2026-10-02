// Volatility-backdrop derivations, verbatim from
// components/regime/VolBackdropStrip.tsx: the live VIX/VIX3M term-structure
// ratio (falls back to the daily ratio), the per-symbol live last/change, and
// the date-joined ratio sparkline.
import type { RegimeQuotesResponse } from "../useRegimeQuotes";
import type { VolBackdropData } from "../useVolBackdrop";
import { quoteIsFreshAt } from "./gex";

export type VolBackdropSymbol = "VIX" | "VIX3M" | "VVIX" | "COR1M";
export const VOL_BACKDROP_SYMBOLS: VolBackdropSymbol[] = [
  "VIX",
  "VIX3M",
  "VVIX",
  "COR1M",
];

export function lastClose(
  points: { close: number }[] | undefined,
): number | null {
  if (!points || !points.length) return null;
  return points[points.length - 1].close;
}

export function pctChange(
  points: { close: number }[] | undefined,
): number | null {
  if (!points || points.length < 2) return null;
  const prev = points[points.length - 2].close;
  const last = points[points.length - 1].close;
  if (!prev) return null;
  return ((last - prev) / prev) * 100;
}

/** Live term structure when both legs are fresh; falls back to daily ratio. */
export function termStructureRead(
  data: VolBackdropData,
  quotes: RegimeQuotesResponse | null | undefined,
  now: number = Date.now(),
): {
  liveRatio: number | null;
  ratio: number | null;
  state: "contango" | "backwardation" | null;
  ratioSource: "live" | "eod";
} {
  const freshWindow = quotes?.fresh_within_seconds;
  const qv = quotes?.quotes?.VIX;
  const q3 = quotes?.quotes?.VIX3M;
  const liveRatio =
    qv &&
    q3 &&
    quoteIsFreshAt(qv.quoted_at, freshWindow, now) &&
    quoteIsFreshAt(q3.quoted_at, freshWindow, now) &&
    q3.price
      ? qv.price / q3.price
      : null;
  const ratio = liveRatio ?? data.term_structure_ratio;
  const state =
    ratio != null
      ? ratio < 1
        ? "contango"
        : "backwardation"
      : data.term_structure_state;
  return {
    liveRatio,
    ratio,
    state,
    ratioSource: liveRatio != null ? "live" : "eod",
  };
}

/** Daily VIX/VIX3M ratio series, joined by date (verbatim). */
export function ratioSeries(data: VolBackdropData): (number | null)[] {
  const vix3mByDate = new Map(
    (data.series.VIX3M ?? []).map((p) => [p.date, p.close]),
  );
  return (data.series.VIX ?? []).map((p) => {
    const v3 = vix3mByDate.get(p.date);
    return v3 ? p.close / v3 : null;
  });
}

/**
 * Per-symbol tile values, verbatim: a fresh quote shows `price` with change
 * vs the last daily close (intraday ret_1d convention); otherwise the last
 * daily close and close-over-close pctChange.
 */
export function symbolRead(
  symbol: VolBackdropSymbol,
  data: VolBackdropData,
  quotes: RegimeQuotesResponse | null | undefined,
  now: number = Date.now(),
): {
  live: boolean;
  close: number | null;
  chg: number | null;
} {
  const freshWindow = quotes?.fresh_within_seconds;
  const q = quotes?.quotes?.[symbol];
  const live = q != null && quoteIsFreshAt(q.quoted_at, freshWindow, now);
  const dailyClose = lastClose(data.series[symbol]);
  // Live: current quote with change vs last daily close (intraday
  // ret_1d convention, same as TickerCards). Daily: close-over-close.
  const close = live ? q.price : dailyClose;
  const chg =
    live && dailyClose
      ? ((q.price - dailyClose) / dailyClose) * 100
      : pctChange(data.series[symbol]);
  return { live, close, chg };
}
