import {
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type LineData,
  type Time,
  type WhitespaceData,
} from "lightweight-charts";
import { type TechnicalsResponse } from "@/lib/api";
import { type SeriesRow } from "@/lib/priceChartData";
import { fmtVolCompact } from "@/lib/indicators";
import { macdSignalText, type DualMacdDetail } from "@/lib/technicals/verdicts";
import { BandsIndicator, type BandPoint } from "@/lib/lwc/bandsIndicator";
import { ChanlunZhongshu } from "@/lib/lwc/chanlunZhongshu";
import { VolumeProfileIndicator } from "@/lib/lwc/volumeProfile";

export const H = 460;
// Dual-MACD sub-pane rides below price in the SAME chart instance — one shared
// time scale gives locked scroll + pixel-perfect x-alignment for free (v5 panes).
export const MACD_H = 150;

// Canvas needs concrete colors — resolve the Argon CSS variables at mount.
export function cssVar(name: string): string {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || "#888888";
}

// Dual-MACD badge for the sub-pane: the tactical signal (or trend state) plus a
// directional color. Backend trend_state ∈ {BULLISH, BEARISH, DETERIORATING,
// IMPROVING} (cards/technicals.py dual_macd_state). Clean bull/bear → full
// green/red; the two transitional states color by their structure sign but at a
// dimmed shade — DETERIORATING = bull cooling (dim green), IMPROVING = bear
// recovering (dim red) — so "in transition" reads distinctly from a clean trend.
// ponytail: color-mix dims a token toward muted — no per-shade CSS var needed.
export const dim = (token: string) =>
  `color-mix(in srgb, ${token} 55%, var(--text-muted))`;
export function macdSignal(
  dm: DualMacdDetail | undefined,
): { text: string; color: string } | null {
  // Text + the signal key come from lib/technicals/verdicts; the color mapping
  // below is the pane's drawing choice.
  const sig = macdSignalText(dm);
  if (!sig) return null;
  const key = sig.key.toUpperCase();
  const color = /DETERIORATING/.test(key)
    ? dim("var(--positive)") // bull structure, weakening
    : /IMPROVING/.test(key)
      ? dim("var(--negative)") // bear structure, recovering
      : /BULL|DIP_BUY|\bUP\b|LONG/.test(key)
        ? "var(--positive)"
        : /BEAR|RALLY_SELL|DOWN|SHORT/.test(key)
          ? "var(--negative)"
          : "var(--text-muted)";
  return { text: sig.text, color };
}

// MarketSmith display style; the hover readout still shows true vol.
export const TRUNCATE_VOLUME_AT_2X_MA = false;

// One readout line for both hover and the default last-bar state: OHLC (or
// close) + volume buzz (V + ×MA50 when an MA value exists for the bar).
export function readoutLine(
  time: string,
  bar: {
    open?: number;
    high?: number;
    low?: number;
    close?: number;
    value?: number;
  },
  vol: number | null | undefined,
  volMa: number | undefined,
): string {
  const f = (x?: number) => (x == null ? "–" : x.toFixed(2));
  const buzz =
    vol != null
      ? `  V ${fmtVolCompact(vol)}${volMa ? ` · ${(vol / volMa).toFixed(2)}×MA50` : ""}`
      : "";
  return bar.open != null
    ? `${time}  O ${f(bar.open)} H ${f(bar.high)} L ${f(bar.low)} C ${f(bar.close)}${buzz}`
    : `${time}  C ${f(bar.value)}${buzz}`;
}

export type Anchor = {
  anchorDate: string;
  series: { time: string; value: number }[];
};

export function anchorFromServer(
  va: TechnicalsResponse["vwap_anchor"],
): Anchor | null {
  if (!va) return null;
  return {
    anchorDate: va.anchor_date,
    series: (va.series ?? []).map((p) => ({ time: p.as_of, value: p.vwap })),
  };
}

// Zip a full-length indicator array (index-aligned to `rows`) onto the bars'
// times; null → a whitespace point, so a warm-up or data hole is an explicit
// gap, not an omission. Same emit rule as the old to*LineData mappers.
export function alignedLineData(
  rows: readonly SeriesRow[],
  values: readonly (number | null)[],
): (LineData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r, i) => {
    const v = values[i];
    return v == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: v };
  });
}

// Same for an upper/lower band. `requireSpread` replicates the Bollinger
// mapper's `u > l` gap rule; the ATR band already emits null unless sma20 and
// a positive ATR both exist, so it passes false.
export function alignedBandData(
  rows: readonly SeriesRow[],
  band: {
    upper: readonly (number | null)[];
    lower: readonly (number | null)[];
  },
  requireSpread: boolean,
): BandPoint[] {
  return rows.map((r, i) => {
    const u = band.upper[i];
    const l = band.lower[i];
    const t = r.as_of as Time;
    return u != null && l != null && (!requireSpread || u > l)
      ? { time: t, upper: u, lower: l }
      : { time: t };
  });
}

export type ChartHandles = {
  chart: IChartApi;
  price: ISeriesApi<"Candlestick"> | ISeriesApi<"Line">;
  volume: ISeriesApi<"Histogram"> | null;
  mas: Record<"fast" | "mid" | "slow", ISeriesApi<"Line">>;
  vwap: ISeriesApi<"Line">;
  bands: BandsIndicator;
  volMa: ISeriesApi<"Line"> | null;
  volMarkers: ISeriesMarkersPluginApi<Time> | null;
  macdSlow: ISeriesApi<"Histogram">;
  macdFast: ISeriesApi<"Histogram">;
  macdFastLine: ISeriesApi<"Line">;
  macdFastSignal: ISeriesApi<"Line">;
  biSolid: ISeriesApi<"Line">;
  biDashed: ISeriesApi<"Line">;
  clZs: ChanlunZhongshu;
  clMarkers: ISeriesMarkersPluginApi<Time>;
  segSolid: ISeriesApi<"Line">;
  segDashed: ISeriesApi<"Line">;
  segZs: ChanlunZhongshu;
  vp: VolumeProfileIndicator;
  fvg: ChanlunZhongshu;
};

export const READABLE_BAR_PX = 6; // min bar width before we scroll instead of squish
export const RIGHT_GAP_BARS = 10; // gap (in bar-widths) between the last bar and the price axis
export const TECHNICALS_TIME_SCALE_OPTIONS = {
  rightOffset: RIGHT_GAP_BARS,
  fixLeftEdge: true,
  fixRightEdge: false,
  minBarSpacing: 4,
} as const;

// Hover-only below-bar labels must not participate in autoscaling. The default
// marker behavior reserves bottom margin as soon as a label appears, which
// lifts and compresses the entire volume histogram while moving the crosshair.
export const VOLUME_MARKER_OPTIONS = { autoScale: false } as const;

// Snap the view back to a readable default. If the whole range fits at a
// readable bar width, fit it edge-to-edge. Otherwise (e.g. FULL = 5y) fitContent
// would squish bars to ~1px — instead pin a readable bar width and scroll to the
// newest bars, leaving the rest to scroll left.
export function resetView(h: ChartHandles, barCount: number) {
  const ts = h.chart.timeScale();
  const width = ts.width();
  if (width > 0 && (barCount + RIGHT_GAP_BARS) * READABLE_BAR_PX > width) {
    ts.applyOptions({ barSpacing: READABLE_BAR_PX });
    ts.scrollToPosition(RIGHT_GAP_BARS, false);
  } else {
    // Fit the full short window while explicitly reserving the same right gap.
    ts.setVisibleLogicalRange({ from: 0, to: barCount - 1 + RIGHT_GAP_BARS });
  }
}
