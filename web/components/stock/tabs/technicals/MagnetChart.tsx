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
  const divider = useRef<HTMLDivElement>(null);

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

    // Every series' automatic last-value axis label is suppressed throughout
    // this chart. The five level price-lines own the right axis; leaving the
    // defaults on adds a bare SMA20 tag and prints the last close TWICE more
    // (candles + ZigZag), which collides with the explicit LAST label and puts
    // three unlabelled numbers on an axis whose whole job is naming levels.
    const price = chart.addSeries(CandlestickSeries, {
      upColor: "#4ade80",
      downColor: "#fb7185",
      borderVisible: false,
      wickUpColor: "#4ade80",
      wickDownColor: "#fb7185",
      lastValueVisible: false,
      priceLineVisible: false,
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
    const ma = chart.addSeries(LineSeries, {
      color: "#c4b5fd",
      lineWidth: 2,
      lastValueVisible: false,
      priceLineVisible: false,
    });
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
        lastValueVisible: false,
        priceLineVisible: false,
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

    // BB(20,2sigma) on the candle series — same primitive as the level zones.
    const closes20 = data.candles.map((c) => c.close);
    const bb = new BandsIndicator({
      lineColor: "transparent",
      fillColor: "rgba(196,181,253,0.10)",
      lineWidth: 1,
    });
    price.attachPrimitive(bb);
    bb.setBandData(
      data.candles.map((c, i) => {
        // BandPoint allows {time} with no upper/lower — that is how the first 19
        // bars are represented, and contiguousValidRuns splits the fill on those
        // gaps rather than interpolating across the warm-up.
        if (i < 19) return { time: c.date as Time };
        const w = closes20.slice(i - 19, i + 1);
        const m = w.reduce((a, x) => a + x, 0) / 20;
        const sd = Math.sqrt(w.reduce((a, x) => a + (x - m) ** 2, 0) / 20);
        return { time: c.date as Time, upper: m + 2 * sd, lower: m - 2 * sd };
      }),
    );

    // The options-implied cone: twelve short segments radiating from the last
    // bar (3 horizons x 2 sigmas x upper/lower). Plain LineSeries, the shape
    // DensityConeChart.tsx:355-380 already uses — no primitive needed.
    const lastBar = data.candles[data.candles.length - 1]!;
    // Horizon in CALENDAR days so the right-edge distance is proportional to what
    // the band means. Same h*7/5 mapping the calibration used for target_dte.
    const future = (tradingDays: number) => {
      const d = new Date(`${lastBar.date}T00:00:00Z`);
      d.setUTCDate(d.getUTCDate() + Math.round((tradingDays * 7) / 5));
      return d.toISOString().slice(0, 10) as Time;
    };

    for (const b of data.bands) {
      const t = future(b.horizon);
      for (const edge of [b.upper, b.lower]) {
        const s = chart.addSeries(LineSeries, {
          // 1.96σ is the quoted band, so it is the more visible one.
          color: b.band_sigma === 1.96 ? "#38bdf8cc" : "#38bdf866",
          lineWidth: 1,
          lineStyle: LineStyle.Solid,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        s.setData([
          { time: lastBar.date as Time, value: lastBar.close },
          { time: t, value: edge },
        ]);
      }
    }

    // Divider caption at the last bar: it is what makes the right edge legible
    // as projection rather than data. Plain absolutely-positioned DOM, not a
    // chart primitive — it is a static caption, and a primitive for it would be
    // the same mistake as the scenarioPaths.ts this plan already cut.
    //
    // It reads "options-implied", not the spec's "scenarios": the scenario paths
    // were cut (spec §1.2 replaces the fan with the cone), so the only thing
    // right of this line is the cone. Naming it "scenarios" would label
    // something that is not drawn.
    const placeDivider = () => {
      const x = chart.timeScale().timeToCoordinate(lastBar.date as Time);
      if (x == null || !divider.current) return;
      divider.current.style.left = `${x}px`;
      divider.current.style.visibility = "visible";
    };
    chart.timeScale().subscribeVisibleTimeRangeChange(placeDivider);
    chart.timeScale().fitContent();
    placeDivider();
    return () => {
      chart.timeScale().unsubscribeVisibleTimeRangeChange(placeDivider);
      chart.remove();
    };
  }, [data]);

  return (
    <div style={{ position: "relative", width: "100%" }}>
      <div data-testid="magnet-chart" ref={host} style={{ width: "100%" }} />
      <div
        ref={divider}
        style={{
          position: "absolute",
          top: 4,
          transform: "translateX(-50%)",
          visibility: "hidden",
          pointerEvents: "none",
          whiteSpace: "nowrap",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 0.5,
          opacity: 0.55,
        }}
      >
        history ← | → options-implied
      </div>
    </div>
  );
}
