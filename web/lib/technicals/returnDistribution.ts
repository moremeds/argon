// Pure math behind the Return Distribution panel: trailing daily returns, the
// 21-bin histogram over mean ± 3.5σ, and the normal overlay in count units.
// Shared by the React panel and the Node MCP tools — same inputs + same
// function = same rendered number. Plain data in and out; the panel maps it
// onto svgChart scales.
import type { TechnicalsResponse } from "@/lib/api";

export type SeriesRow = TechnicalsResponse["series"][number];

/** Trailing sessions of daily returns the histogram covers. */
export const RETURN_WINDOW = 60;
/** Histogram resolution — 21 bins over mean ± 3.5σ, outliers clamped. */
export const RETURN_NBINS = 21;
/** The skew headline and normal overlay need a real fit: n >= 20 and sd > 0. */
const MIN_N = 20;

export type Bins = {
  edges: number[];
  counts: number[];
  mean: number;
  sd: number;
};

// Pure: bin `returns` into `nbins` over [mean-3.5σ, mean+3.5σ] (outliers clamp
// to the edge bins), returning bin edges, counts, and the sample moments.
export function returnBins(returns: number[], nbins = RETURN_NBINS): Bins {
  const empty: Bins = {
    edges: Array.from({ length: nbins + 1 }, (_, i) => i),
    counts: Array(nbins).fill(0),
    mean: 0,
    sd: 0,
  };
  const n = returns.length;
  if (n < 2) return empty;
  const mean = returns.reduce((a, c) => a + c, 0) / n;
  const variance = returns.reduce((a, c) => a + (c - mean) ** 2, 0) / (n - 1);
  const sd = Math.sqrt(variance);
  if (!(sd > 0)) return { ...empty, mean };
  const lo = mean - 3.5 * sd;
  const hi = mean + 3.5 * sd;
  const w = (hi - lo) / nbins;
  const edges = Array.from({ length: nbins + 1 }, (_, i) => lo + i * w);
  const counts = Array(nbins).fill(0);
  for (const r of returns) {
    let idx = Math.floor((r - lo) / w);
    if (idx < 0) idx = 0;
    if (idx >= nbins) idx = nbins - 1;
    counts[idx] += 1;
  }
  return { edges, counts, mean, sd };
}

function normPdf(x: number, mean: number, sd: number): number {
  const z = (x - mean) / sd;
  return Math.exp(-0.5 * z * z) / (sd * Math.sqrt(2 * Math.PI));
}

export type ReturnDistribution = {
  /** Sessions of returns used — `series` non-null closes minus one, capped at
   *  RETURN_WINDOW. */
  n: number;
  mean: number;
  sd: number;
  /** Adjusted Fisher-Pearson skew — null unless n >= 20 and sd > 0. */
  skew: number | null;
  /** The 21-bin histogram (`returnBins(window)`). */
  bins: Bins;
  /** The normal overlay, 121 points spanning [lo, hi] in count units — the
   *  panel scales each to pixels. Null unless n >= 20 and sd > 0. */
  normal: { x: number; count: number }[] | null;
};

// Simple daily returns over the series' non-null closes, last RETURN_WINDOW.
// This is the same input the panel receives today — the live-merged series.
export function returnDistribution(
  series: readonly SeriesRow[],
): ReturnDistribution {
  const closes = series
    .map((r) => r.close)
    .filter((v): v is number => v != null);
  const rets: number[] = [];
  for (let i = 1; i < closes.length; i++) {
    const p = closes[i - 1];
    if (p) rets.push(closes[i] / p - 1);
  }
  const window = rets.slice(-RETURN_WINDOW);
  const bins = returnBins(window, RETURN_NBINS);
  const n = window.length;
  const { mean, sd } = bins;
  const fitted = n >= MIN_N && sd > 0;
  const skew = fitted
    ? (n / ((n - 1) * (n - 2))) *
      window.reduce((a, c) => a + ((c - mean) / sd) ** 3, 0)
    : null;
  // Normal overlay in count units: expected count per bin = n * binWidth * pdf.
  const lo = bins.edges[0];
  const hi = bins.edges[bins.edges.length - 1];
  const w = (hi - lo) / RETURN_NBINS;
  const normal = fitted
    ? Array.from({ length: 121 }, (_, i) => {
        const x = lo + ((hi - lo) * i) / 120;
        return { x, count: n * w * normPdf(x, mean, sd) };
      })
    : null;
  return { n, mean, sd, skew, bins, normal };
}
