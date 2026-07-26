import type {
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  WhitespaceData,
} from "lightweight-charts";
import type { TechnicalsResponse } from "@/lib/api";
import type { BandPoint } from "@/lib/lwc/bandsIndicator";
import {
  atr,
  bollinger,
  ema,
  lowestInWindow,
  prevCloseUp,
  volumeMa,
} from "@/lib/indicators";

export type SeriesRow = TechnicalsResponse["series"][number];

// Candle mode only when the BULK of history carries OHLC — a majority test, not
// `some`. Otherwise a single OHLC row (e.g. the live forming head appended onto a
// not-yet-backfilled close-only history) would flip the whole chart to candle
// mode and render every close-only bar as a flat doji until the backfill lands.
export function hasOhlcv(rows: readonly SeriesRow[]): boolean {
  if (rows.length === 0) return false;
  const withOhlc = rows.filter(
    (r) => r.open != null && r.high != null && r.low != null,
  ).length;
  return withOhlc >= rows.length / 2;
}

export function toCandleData(
  rows: readonly SeriesRow[],
): (CandlestickData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) => {
    const t = r.as_of as Time;
    if (r.close == null) return { time: t };
    if (r.open != null && r.high != null && r.low != null) {
      return {
        time: t,
        open: r.open,
        high: r.high,
        low: r.low,
        close: r.close,
      };
    }
    // OHLC-less row in candle mode (e.g. a live head appended for a new
    // session): flat tick at the close.
    return {
      time: t,
      open: r.close,
      high: r.close,
      low: r.close,
      close: r.close,
    };
  });
}

export function toCloseLineData(
  rows: readonly SeriesRow[],
): (LineData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) =>
    r.close == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: r.close },
  );
}

export function toSmaLineData(
  rows: readonly SeriesRow[],
  key: "sma20" | "sma50" | "sma200",
): (LineData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) => {
    const v = r[key];
    return v == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: v };
  });
}

// Highlight the EXTREMES of volume, not the magnitude. Opacity is U-shaped in
// "buzz" (volume ÷ its volume-MA): bars in line with their MA recede to a muted
// baseline, while both tails — an extreme-high blowoff AND an extreme-low
// dry-up — saturate to full opacity so they pop off the chart. The low tail is
// intentionally steeper (full highlight by ≤0.4×MA vs ≥2×MA on the high side):
// a quiet bar is short and easy to miss, so we make light volume shout. Hue
// always stays the bar's up/down red/green — never gray.
function alphaFromBuzz(vol: number, ma: number | null | undefined): number {
  if (ma == null || ma <= 0) return 0.6; // warmup: no MA yet → muted baseline
  const buzz = vol / ma;
  const extremeness =
    buzz >= 1
      ? Math.min(1, buzz - 1) // full highlight at ≥2×MA
      : Math.min(1, (1 - buzz) / 0.6); // full highlight at ≤0.4×MA (steeper)
  return 0.5 + extremeness * 0.5; // muted 0.5 → extreme 1.0
}

// 0..1 alpha → 2-digit hex, appended to a #RRGGBB color to form a canvas-legal
// #RRGGBBAA. Assumes 6-digit-hex base colors (the Argon CSS vars are).
function alphaHex(a: number): string {
  return Math.round(Math.max(0, Math.min(1, a)) * 255)
    .toString(16)
    .padStart(2, "0");
}

// MarketSmith volume treatment: direction by PREVIOUS close (not bar
// direction), optional graying of lowest-in-window bars, optional display cap
// (2×MA truncation) — the hover readout still shows the true volume. When a
// `magnitude` array (the volume MA) is supplied, each bar's opacity scales with
// its volume/MA ratio so larger volume → deeper shade of its hue.
export function toVolumeData(
  rows: readonly SeriesRow[],
  upColor: string,
  downColor: string,
  opts?: {
    lowColor?: string;
    lowWindow?: number;
    truncateAt?: readonly (number | null)[];
    magnitude?: readonly (number | null)[];
  },
): (HistogramData<Time> | WhitespaceData<Time>)[] {
  const up = prevCloseUp(rows);
  const low = opts?.lowColor
    ? lowestInWindow(
        rows.map((r) => r.volume),
        opts.lowWindow ?? 10,
      )
    : null;
  return rows.map((r, i) => {
    const t = r.as_of as Time;
    if (r.volume == null) return { time: t };
    const cap = opts?.truncateAt?.[i];
    const value = cap != null ? Math.min(r.volume, cap) : r.volume;
    const base = low?.[i]
      ? (opts!.lowColor as string)
      : (up[i] ?? true)
        ? upColor
        : downColor;
    // Buzz uses the TRUE volume, never the truncated display value.
    const color = opts?.magnitude
      ? base + alphaHex(alphaFromBuzz(r.volume, opts.magnitude[i]))
      : base;
    return { time: t, value, color };
  });
}

// Keltner-style ATR envelope: sma20 ± mult · ATR(period). Replaces the old
// ±1.5σ-around-sma200 band, which was a slow-moving cloud price rarely touched.
export function toAtrBandData(
  rows: readonly SeriesRow[],
  period = 14,
  mult = 2,
): BandPoint[] {
  const a = atr(
    rows.map((r) => r.high),
    rows.map((r) => r.low),
    rows.map((r) => r.close),
    period,
  );
  const out: BandPoint[] = [];
  rows.forEach((r, i) => {
    const m = r.sma20;
    const v = a[i];
    if (m != null && v != null && v > 0) {
      out.push({
        time: r.as_of as Time,
        upper: m + mult * v,
        lower: m - mult * v,
      });
    }
  });
  return out;
}

export function toEmaLineData(
  rows: readonly SeriesRow[],
  period: number,
): (LineData<Time> | WhitespaceData<Time>)[] {
  const e = ema(
    rows.map((r) => r.close),
    period,
  );
  return rows.map((r, i) =>
    e[i] == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: e[i] as number },
  );
}

export function toBollingerBandData(
  rows: readonly SeriesRow[],
  period = 20,
  mult = 2,
): BandPoint[] {
  const bb = bollinger(
    rows.map((r) => r.close),
    period,
    mult,
  );
  const out: BandPoint[] = [];
  rows.forEach((r, i) => {
    const u = bb.upper[i];
    const l = bb.lower[i];
    if (u != null && l != null && u > l) {
      out.push({ time: r.as_of as Time, upper: u, lower: l });
    }
  });
  return out;
}

export function toVolumeMaData(
  rows: readonly SeriesRow[],
  period = 50,
): (LineData<Time> | WhitespaceData<Time>)[] {
  const ma = volumeMa(
    rows.map((r) => r.volume),
    period,
  );
  return rows.map((r, i) =>
    ma[i] == null
      ? { time: r.as_of as Time }
      : { time: r.as_of as Time, value: ma[i] as number },
  );
}
