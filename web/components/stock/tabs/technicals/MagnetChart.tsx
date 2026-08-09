"use client";

import { useEffect, useRef } from "react";
import {
  CandlestickSeries,
  LineSeries,
  LineStyle,
  createChart,
  createSeriesMarkers,
  type IChartApi,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";

import type { MagnetsResponse } from "@/lib/api";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { MAGNET_COLORS } from "./MagnetTable";

const BAND_HALF_WIDTH = 0.0025; // 0.25% of the level — a zone, not a hairline

function sma(values: number[], n: number): (number | null)[] {
  const out: (number | null)[] = [];
  let sum = 0;
  for (let i = 0; i < values.length; i++) {
    sum += values[i]!;
    if (i >= n) sum -= values[i - n]!;
    out.push(i >= n - 1 ? sum / n : null);
  }
  return out;
}

export default function MagnetChart({ data }: { data: MagnetsResponse }) {
  const host = useRef<HTMLDivElement>(null);

  useEffect(() => {
    if (!host.current || data.candles.length === 0) return;
    const chart: IChartApi = createChart(host.current, {
      autoSize: true, // house pattern (DensityConeChart.tsx:117) — no ResizeObserver
      height: 420,
      layout: { background: { color: "transparent" }, textColor: "#94a3b8" },
      grid: {
        vertLines: { color: "rgba(255,255,255,0.04)" },
        horzLines: { color: "rgba(255,255,255,0.04)" },
      },
      rightPriceScale: { borderVisible: false },
      timeScale: { borderVisible: false, rightOffset: 24 },
    });

    const price = chart.addSeries(CandlestickSeries, {
      upColor: "#4ade80",
      downColor: "#fb7185",
      borderVisible: false,
      wickUpColor: "#4ade80",
      wickDownColor: "#fb7185",
    });
    price.setData(
      data.candles.map((c) => ({
        time: c.date as Time,
        open: c.open,
        high: c.high,
        low: c.low,
        close: c.close,
      })),
    );

    const closes = data.candles.map((c) => c.close);
    const ma = chart.addSeries(LineSeries, { color: "#c4b5fd", lineWidth: 2 });
    ma.setData(
      sma(closes, 20)
        .map((v, i) =>
          v == null ? null : { time: data.candles[i]!.date as Time, value: v },
        )
        .filter((x): x is { time: Time; value: number } => x !== null),
    );

    // ZigZag polyline through the confirmed pivots, plus the last close so the
    // live leg is visible. Pivot indices are already rebased to `candles`.
    if (data.pivots.length >= 2) {
      const zig = chart.addSeries(LineSeries, {
        color: "#818cf8",
        lineWidth: 2,
        lineStyle: LineStyle.Dashed,
        crosshairMarkerVisible: false,
      });
      const last = data.candles[data.candles.length - 1]!;
      zig.setData([
        ...data.pivots.map((p) => ({
          time: data.candles[p.index]!.date as Time,
          value: p.price,
        })),
        { time: last.date as Time, value: last.close },
      ]);
    }

    // A / B markers on the last two pivots only — the reference labels exactly two.
    const ab = data.pivots.slice(-2);
    const markers: SeriesMarker<Time>[] = ab.map((p, i) => ({
      time: data.candles[p.index]!.date as Time,
      position: p.kind === "top" ? "aboveBar" : "belowBar",
      color: p.kind === "top" ? "#fb7185" : "#4ade80",
      shape: p.kind === "top" ? "arrowDown" : "arrowUp",
      text: i === 0 ? "A" : "B",
    }));
    createSeriesMarkers(price, markers);

    // Five levels: a solid core price-line plus a FILLED translucent zone.
    // createPriceLine cannot fill, so the zone is a BandsIndicator — the same
    // primitive TechnicalsPriceChart.tsx:500-505 attaches for BB.
    if (data.levels) {
      const lv = data.levels;
      const first = data.candles[0]!.date as Time;
      // The zone must reach PAST the last candle, into the projection zone where
      // Task 7 draws the cone. That overlap is the whole read: a 0.618 level whose
      // zone runs outside the cone is visibly outside it. Stopping the zone at the
      // last bar would leave the two objects on disjoint x-ranges and there would
      // be nothing to compare. 30 calendar days covers the 21d horizon (~29d).
      const lastBarDate = data.candles[data.candles.length - 1]!.date;
      const edge = new Date(`${lastBarDate}T00:00:00Z`);
      edge.setUTCDate(edge.getUTCDate() + 30);
      const last = edge.toISOString().slice(0, 10) as Time;
      const levels: [number, string, LineStyle, string][] = [
        [lv.stretch, MAGNET_COLORS.stretch, LineStyle.Dashed, "STRETCH"],
        [
          lv.resistance,
          MAGNET_COLORS.resistance,
          LineStyle.Solid,
          "RESISTANCE",
        ],
        [lv.last, MAGNET_COLORS.last, LineStyle.Dashed, "LAST"],
        [lv.support, MAGNET_COLORS.support, LineStyle.Solid, "SUPPORT"],
        [lv.down, MAGNET_COLORS.down, LineStyle.Dashed, "DOWN"],
      ];
      for (const [value, color, style, title] of levels) {
        price.createPriceLine({
          price: value,
          color,
          lineWidth: 2,
          lineStyle: style,
          axisLabelVisible: true,
          title,
        });
        // Two points at constant values = a horizontal filled zone spanning the
        // drawn window. `${color}22` is ~13% alpha: readable as an area, never
        // competing with the candles.
        const zone = new BandsIndicator({
          lineColor: "transparent",
          fillColor: `${color}22`,
          lineWidth: 1,
        });
        price.attachPrimitive(zone);
        zone.setBandData([
          {
            time: first,
            upper: value * (1 + BAND_HALF_WIDTH),
            lower: value * (1 - BAND_HALF_WIDTH),
          },
          {
            time: last,
            upper: value * (1 + BAND_HALF_WIDTH),
            lower: value * (1 - BAND_HALF_WIDTH),
          },
        ]);
      }
    }

    chart.timeScale().fitContent();
    return () => chart.remove();
  }, [data]);

  return (
    <div data-testid="magnet-chart" ref={host} style={{ width: "100%" }} />
  );
}
