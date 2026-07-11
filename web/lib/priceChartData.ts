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

// MarketSmith volume treatment: direction by PREVIOUS close (not bar
// direction), optional graying of lowest-in-window bars, optional display cap
// (2×MA truncation) — the hover readout still shows the true volume.
export function toVolumeData(
  rows: readonly SeriesRow[],
  upColor: string,
  downColor: string,
  opts?: {
    lowColor?: string;
    lowWindow?: number;
    truncateAt?: readonly (number | null)[];
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
    const color = low?.[i]
      ? (opts!.lowColor as string)
      : (up[i] ?? true)
        ? upColor
        : downColor;
    return { time: t, value, color };
  });
}

// ±1.5σ envelope recovered from stored z exactly as the retired SVG pane did:
// half = 1.5 * (close - sma200) / z, where z = (close - sma200) / sigma.
export function toBandData(rows: readonly SeriesRow[]): BandPoint[] {
  const out: BandPoint[] = [];
  for (const r of rows) {
    const c = r.close;
    const m = r.sma200;
    const z = r.z;
    if (c != null && m != null && z != null && z !== 0 && Number.isFinite(z)) {
      const half = 1.5 * ((c - m) / z);
      out.push({ time: r.as_of as Time, upper: m + half, lower: m - half });
    }
  }
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
    if (u != null && l != null) {
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
