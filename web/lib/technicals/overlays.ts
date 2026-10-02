// Every browser-computed value the Technicals price pane draws — EMAs, the
// Bollinger/ATR bands, volume MA + markers, chanlun, volume profile, FVG —
// behind ONE pure function shared by the React chart and the Node MCP tools.
// Same inputs + same function = the same rendered number. Plain data out (no
// chart-lib types); the chart maps it onto lwc shapes.
//
// Indicators compute over `data.series` (the full, live-merged history — the
// warmup rows before the window are what converge EMA/BB/ATR) and the chart
// cuts at `firstAsOf` for display. FVG is the exception: it runs on the
// timeframe-windowed `rows`, matching the pane.
import type { TechnicalsResponse } from "@/lib/api";
import {
  computeChanlunFull,
  divergenceTrend,
  type ChanlunBar,
  type ChanlunFullResult,
} from "@/lib/chanlun";
import {
  findFairValueGaps,
  type FairValueGap,
  type FvgBar,
} from "@/lib/fvg";
import {
  atr,
  bollinger,
  ema,
  highVolMarkers,
  lowVolMarkers,
  volumeMa,
  type VolMarker,
} from "@/lib/indicators";
import {
  buildStats,
  computeVolumeProfile,
  findLvnLevels,
  findSrZones,
  type SrZone,
  type VolumeProfile,
  type VolumeProfileStats,
  type VpBar,
} from "@/lib/volumeProfile";
import { sliceSeriesByTimeframe, type Timeframe } from "./series";

export type SeriesRow = TechnicalsResponse["series"][number];

// MarketSmith knobs — the constants the chart drew with, now defined once here.
export const VOL_MA_PERIOD = 50;
export const LOW_VOL_THRESHOLD_PCT = -25;
// Sessions the volume profile covers, counted back from the newest bar. Fixed,
// not the visible range — panning a visible-range profile moved the POC by a
// median of 11.6 ATR. 360 keeps the levels within ~10-20% of spot; longer
// windows are steadier but anchor to prices the market has left behind.
// docs/research/2026-07-20-volume-profile-window-study.md
export const VP_LOOKBACK = 360;
const VP_BINS = 60;
const VP_VALUE_PCT = 70;

/** A volume-marker spec sans color — the chart resolves theme colors itself. */
export type OverlayMarker = Omit<VolMarker, "color">;

/** A VP bar with its session date — `time` matches the chart's string times. */
export type VpSeriesBar = VpBar & { time: string };

export type TechnicalsOverlays = {
  /** `sliceSeriesByTimeframe(data.series ?? [], timeframe)` — the window. */
  rows: SeriesRow[];
  /** Display cut: values computed on `full` are drawn only at/after this date
   *  (the chart's `time >= firstAsOf` filter). "" when the window is empty. */
  firstAsOf: string;

  // — full-history indicator arrays, index-aligned to `data.series` —
  ema5: (number | null)[];
  ema20: (number | null)[];
  ema50: (number | null)[];
  /** Bollinger(20, 2, population sd) — raw band; the chart gaps where u <= l. */
  bollinger: { upper: (number | null)[]; lower: (number | null)[] };
  /** Server sma20 ± 2·ATR(14, Wilder) — null where either input is missing
   *  or ATR <= 0 (same emit rule as the old toAtrBandData). */
  atrBand: { upper: (number | null)[]; lower: (number | null)[] };
  volMa50: (number | null)[];
  markers: {
    /** HVE/HV1 (oneYear 252, peakLen 9), deduped ±peakLen. */
    highVol: OverlayMarker[];
    /** Volume <= LOW_VOL_THRESHOLD_PCT vs its volMa50. */
    lowVol: OverlayMarker[];
  };

  chanlun: {
    /** `full` rows with as_of, high, low and close all non-null. */
    bars: ChanlunBar[];
    /** computeChanlunFull(bars) — the full structure, not display-cut. */
    result: ChanlunFullResult;
    /** divergenceTrend(bars, result.divergences) — index-aligned flags. */
    divergenceTrend: (boolean | null)[];
  };

  vp: {
    /** `full` rows with OHLCV all non-null, in order — feed to the primitive. */
    bars: VpSeriesBar[];
    /** The last VP_LOOKBACK of `bars` — what profile/zones/lvn/stats describe. */
    window: VpSeriesBar[];
    /** computeVolumeProfile(window, 60, 70); null on <2 bars or zero range. */
    profile: VolumeProfile | null;
    zones: SrZone[]; // findSrZones(profile, window, last.close), engine defaults
    lvn: number[]; // findLvnLevels(profile, last.close), engine defaults
    stats: VolumeProfileStats | null; // buildStats(profile, zones, last.close)
  };

  fvg: {
    /** `rows` (the window) with as_of, high and low non-null. */
    bars: FvgBar[];
    /** findFairValueGaps(bars) — unfilled gaps, default maxCount 6. */
    gaps: FairValueGap[];
  };
};

export function technicalsOverlays(
  data: TechnicalsResponse,
  timeframe: Timeframe,
): TechnicalsOverlays {
  const full = (data.series ?? []) as SeriesRow[];
  const rows = sliceSeriesByTimeframe(full, timeframe);
  const firstAsOf = rows[0]?.as_of ?? "";

  const closes = full.map((r) => r.close);
  const atr14 = atr(
    full.map((r) => r.high),
    full.map((r) => r.low),
    closes,
    14,
  );
  const atrBand = {
    upper: full.map((r, i) => {
      const m = r.sma20;
      const v = atr14[i];
      return m != null && v != null && v > 0 ? m + 2 * v : null;
    }),
    lower: full.map((r, i) => {
      const m = r.sma20;
      const v = atr14[i];
      return m != null && v != null && v > 0 ? m - 2 * v : null;
    }),
  };

  const volMa50 = volumeMa(
    full.map((r) => r.volume),
    VOL_MA_PERIOD,
  );
  const strip = (m: VolMarker): OverlayMarker => ({
    time: m.time,
    position: m.position,
    shape: m.shape,
    text: m.text,
    size: m.size,
  });

  const clBars: ChanlunBar[] = full.flatMap((r) =>
    r.as_of != null && r.high != null && r.low != null && r.close != null
      ? [{ time: r.as_of, high: r.high, low: r.low, close: r.close }]
      : [],
  );
  const chanlunResult = computeChanlunFull(clBars);

  const vpBars: VpSeriesBar[] = full.flatMap((r) =>
    r.as_of != null &&
    r.open != null &&
    r.high != null &&
    r.low != null &&
    r.close != null &&
    r.volume != null
      ? [
          {
            time: r.as_of,
            open: r.open,
            high: r.high,
            low: r.low,
            close: r.close,
            volume: r.volume,
          },
        ]
      : [],
  );
  // The most recent VP_LOOKBACK sessions — the primitive's own window rule.
  const vpWindow =
    vpBars.length > VP_LOOKBACK ? vpBars.slice(-VP_LOOKBACK) : vpBars;
  const vpLast = vpWindow[vpWindow.length - 1];
  const profile = computeVolumeProfile(vpWindow, VP_BINS, VP_VALUE_PCT);
  const zones = profile && vpLast ? findSrZones(profile, vpWindow, vpLast.close) : [];
  const lvn = profile && vpLast ? findLvnLevels(profile, vpLast.close) : [];
  const stats =
    profile && vpLast ? buildStats(profile, zones, vpLast.close) : null;

  const fvgBars: FvgBar[] = rows.flatMap((r) =>
    r.as_of != null && r.high != null && r.low != null
      ? [{ time: r.as_of, high: r.high, low: r.low }]
      : [],
  );

  return {
    rows,
    firstAsOf,
    ema5: ema(closes, 5),
    ema20: ema(closes, 20),
    ema50: ema(closes, 50),
    bollinger: bollinger(closes, 20, 2),
    atrBand,
    volMa50,
    markers: {
      highVol: highVolMarkers(full, { color: "" }).map(strip),
      lowVol: lowVolMarkers(full, volMa50, {
        thresholdPct: LOW_VOL_THRESHOLD_PCT,
        color: "",
      }).map(strip),
    },
    chanlun: {
      bars: clBars,
      result: chanlunResult,
      divergenceTrend: divergenceTrend(clBars, chanlunResult.divergences),
    },
    vp: { bars: vpBars, window: vpWindow, profile, zones, lvn, stats },
    fvg: { bars: fvgBars, gaps: findFairValueGaps(fvgBars) },
  };
}
