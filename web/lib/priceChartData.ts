import type {
  CandlestickData,
  HistogramData,
  LineData,
  Time,
  WhitespaceData,
} from "lightweight-charts";
import type { TechnicalsResponse } from "@/lib/api";
import type { BandPoint } from "@/lib/lwc/bandsIndicator";

export type SeriesRow = TechnicalsResponse["series"][number];

export function hasOhlcv(rows: readonly SeriesRow[]): boolean {
  return rows.some((r) => r.open != null && r.high != null && r.low != null);
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

export function toVolumeData(
  rows: readonly SeriesRow[],
  upColor: string,
  downColor: string,
): (HistogramData<Time> | WhitespaceData<Time>)[] {
  return rows.map((r) => {
    const t = r.as_of as Time;
    if (r.volume == null) return { time: t };
    const up = r.open == null || r.close == null || r.close >= r.open;
    return { time: t, value: r.volume, color: up ? upColor : downColor };
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
