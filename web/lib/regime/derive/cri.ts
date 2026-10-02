// CRI derivations, verbatim from components/regime/CriSubTab.tsx: the
// prior-day component scorer, the previous-close lookups, the VVIX/VIX ratio
// fallback, the daily-series projection, VIX Δ3d, and the SPX median filter.
//
// Type-only imports from the components are erased at build — they keep the
// signatures identical to what the component passes.
import type { CriHistoryEntry } from "@/components/regime/CriHistoryChart";
import type { ComponentSlot } from "@/components/regime/primitives/ComponentBar";
import type { CriLiveResponse } from "../useCriLive";
import type { CriDailyEntry } from "../useCriSeries";

// Mirror the Python scoring math from src/uw_scan/cards/cri_scorers.py so we
// can draw the prior-day dot on each ComponentBar. Floors/ceilings MUST match
// cri-methodology.md §3.
//
// v3 (2026-05-20): VIX floor 13 + RoC denom 40; VVIX floor 80; momentum
// reshaped into structural (0-15) + tactical (0-10) sub-scores.
//
// Moved verbatim from CriSubTab.tsx — that file re-exports it so existing
// imports keep working.
export function priorComponentScore(
  prior: CriHistoryEntry | undefined,
  slot: ComponentSlot,
): number | null {
  if (!prior) return null;
  const clip = (x: number, lo: number, hi: number) =>
    Math.max(lo, Math.min(hi, x));
  const round1 = (x: number) => Math.round(x * 10) / 10;
  if (slot === "vix") {
    // v3: floor 13, RoC denom 40 (was 15 / 60)
    if (prior.vix == null || prior.vix_5d_roc == null) return null;
    const lvl = clip(((prior.vix - 13) / 27) * 15, 0, 15);
    const roc = clip((Math.max(prior.vix_5d_roc, 0) / 40) * 10, 0, 10);
    return round1(lvl + roc);
  }
  if (slot === "vvix") {
    // v3: level floor 80 (was 85); ratio band 5-8 and RoC denom 25 unchanged
    if (prior.vvix == null || prior.vix == null || prior.vix <= 0) return null;
    const ratio = prior.vvix / prior.vix;
    const lvl = clip(((prior.vvix - 80) / 50) * 12, 0, 12);
    const r = clip(((ratio - 5) / 3) * 7, 0, 7);
    // vvix_5d_roc was added in v2 — historical snapshots may not have it.
    const rocRaw = prior.vvix_5d_roc ?? 0;
    const roc = clip((Math.max(rocRaw, 0) / 25) * 6, 0, 6);
    return round1(lvl + r + roc);
  }
  if (slot === "correlation") {
    // Unchanged across versions
    if (prior.cor1m == null) return null;
    const lvl = clip(((prior.cor1m - 25) / 45) * 17, 0, 17);
    const chg = prior.cor1m_5d_change ?? 0;
    const spike = clip((Math.max(chg, 0) / 20) * 8, 0, 8);
    return round1(lvl + spike);
  }
  if (slot === "momentum") {
    // v3: structural (0-15, vs 100d MA) + tactical (0-10, vs 20d high, sat -4%)
    if (prior.spx_vs_ma_pct == null) return null;
    const d = prior.spx_vs_ma_pct;
    const structural = d >= 0 ? 0 : clip((Math.abs(d) / 10) * 15, 0, 15);
    // pullback_20d_pct is a v3 history-entry field. Historical (pre-v3) rows
    // won't have it; default to 0 (tactical sub-score doesn't fire).
    const pullback = prior.pullback_20d_pct ?? 0;
    const tactical =
      pullback >= 0 ? 0 : clip((Math.abs(pullback) / 4) * 10, 0, 10);
    return round1(clip(structural + tactical, 0, 25));
  }
  return null;
}

// Pull prior-day values for DayChange from the history array (snapshot stored
// the trailing 20 sessions including today). Today's close lives in the snapshot
// scalars; "previous close" is history[history.length - 2][key].
export function prevClose(
  history: CriHistoryEntry[] | undefined,
  key: keyof CriHistoryEntry,
): number | null {
  if (!history || history.length < 2) return null;
  const v = history[history.length - 2][key];
  return typeof v === "number" && Number.isFinite(v) ? v : null;
}

/** The component's previous-close set + the COR1M payload fallback, verbatim. */
export function criPrevCloses(data: CriLiveResponse): {
  vixClose: number | null;
  vvixClose: number | null;
  spyClose: number | null;
  cor1mPrevClose: number | null;
} {
  const history = (data.history ?? []) as CriHistoryEntry[];
  return {
    vixClose: prevClose(history, "vix"),
    vvixClose: prevClose(history, "vvix"),
    spyClose: prevClose(history, "spy"),
    cor1mPrevClose: data.cor1m_previous_close ?? prevClose(history, "cor1m"),
  };
}

/** VVIX/VIX ratio with the live payload fallback, verbatim. */
export function vvixVixRatio(data: CriLiveResponse): number | null {
  const vix = data.vix ?? null;
  const vvix = data.vvix ?? null;
  return (
    data.vvix_vix_ratio ?? (vix && vix > 0 && vvix != null ? vvix / vix : null)
  );
}

/** The component's `dseries`: project one key, non-finite → null. */
export function criDailySeries(
  dailyRows: CriDailyEntry[],
  k: keyof CriDailyEntry,
): (number | null)[] {
  return dailyRows.map((r) => {
    const v = r[k];
    return typeof v === "number" && Number.isFinite(v) ? v : null;
  });
}

// VIX Δ (3d) has no daily column — derive it from the VIX series, matching
// the tile's definition (absolute change over the last 3 sessions).
export function vixDelta3dSeries(
  dailyRows: CriDailyEntry[],
): (number | null)[] {
  const vixDaily = criDailySeries(dailyRows, "vix");
  return vixDaily.map((v, i) => {
    const base = i >= 3 ? vixDaily[i - 3] : null;
    return v != null && base != null ? v - base : null;
  });
}

// Historical rows can mix SPX- and SPY-scale values when a snapshot captured
// the SPY fallback (observed in dev: 739.17 amid ~7400). Drop points outside
// a 2× band around the median — the index can't halve or double inside the
// 90d window, so only cross-scale points are removed.
export function spxMedianFiltered(dailyRows: CriDailyEntry[]): {
  median: number | null;
  series: (number | null)[];
} {
  const spxDailyRaw = criDailySeries(dailyRows, "spx");
  const spxSorted = spxDailyRaw
    .filter((v): v is number => v != null)
    .sort((a, b) => a - b);
  const spxMedian = spxSorted.length
    ? spxSorted[Math.floor(spxSorted.length / 2)]
    : null;
  const series =
    spxMedian == null
      ? spxDailyRaw
      : spxDailyRaw.map((v) =>
          v != null && (v < spxMedian / 2 || v > spxMedian * 2) ? null : v,
        );
  return { median: spxMedian, series };
}

/** Prior-day history row = second-to-last of the trailing window. */
export function priorHistoryRow(
  data: CriLiveResponse,
): CriHistoryEntry | undefined {
  const history = (data.history ?? []) as CriHistoryEntry[];
  return history.length >= 2 ? history[history.length - 2] : undefined;
}
