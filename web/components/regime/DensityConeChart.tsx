"use client";

import { memo, useEffect, useRef } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  LineSeries,
  LineStyle,
  type Time,
} from "lightweight-charts";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { drawableRows } from "@/lib/regime/coneRows";
import { DensityProfile, densityBarsFromBins } from "@/lib/lwc/densityProfile";
import type {
  SpxDensityForecast,
  SpxDensityHorizon,
  SpxGammaLevels,
  SpxPathPoint,
} from "@/lib/regime/useSpxDensity";

export type ConeView = "fan" | "focused";

// Height of the next-session view. The fan scales OFF this — see paneHeight.
const BASE_HEIGHT = 360;
// Ceiling for the fan. A cone whose h=5 tails blow out (a vol shock) would otherwise
// demand a pane taller than the viewport; past this the fan does compress, which is
// the right failure — an unscrollable chart is worse than an uneven candle scale.
const MAX_HEIGHT = 620;

// Outermost first so the inner, denser bands paint on top.
const BANDS: Array<[keyof SpxDensityHorizon, keyof SpxDensityHorizon, number]> =
  [
    ["q05", "q95", 0.1],
    ["q10", "q90", 0.18],
    ["q25", "q75", 0.3],
  ];

function cssVar(name: string, fallback: string): string {
  if (typeof window === "undefined") return fallback;
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || fallback;
}

/** 'YYYY-MM-DD' is a valid lightweight-charts Time; comparing them as strings is
 *  a correct chronological compare, which the whitespace filter below relies on. */
const asTime = (d: string) => d as unknown as Time;

/**
 * Both views must render at the same price-range-per-pixel, or the fan's wider span
 * squashes the identical candles it shares with the next-session view and the two
 * pictures stop being comparable. The pane height is the only free variable that does
 * not cost information: locking the fan to the near range would crop the h=5 90% band,
 * which is the one thing the fan exists to show.
 *
 * scaleMargins is identical across views, so the ratio of DATA spans is the ratio of
 * visible spans — no need to ask lightweight-charts what it autoscaled to.
 */
function paneHeight(
  view: ConeView,
  forecast: SpxDensityForecast,
  recentPath: SpxPathPoint[],
): number {
  if (view === "focused") return BASE_HEIGHT;
  const anchor = forecast.anchor_close;
  const candles: number[] = [anchor];
  for (const p of recentPath) {
    candles.push(p.close);
    if (p.high != null) candles.push(p.high);
    if (p.low != null) candles.push(p.low);
  }
  // Price lines (dealer levels) are excluded on purpose: lightweight-charts does not
  // autoscale to them either, so counting them here would overstate the span.
  const span = (rows: SpxDensityHorizon[], withBaseline: boolean) => {
    const v = [...candles];
    for (const r of rows) {
      v.push(anchor * (1 + r.q05), anchor * (1 + r.q95));
      if (withBaseline)
        v.push(anchor * (1 + r.baseline_q10), anchor * (1 + r.baseline_q90));
    }
    return Math.max(...v) - Math.min(...v);
  };
  const near = span(forecast.rows.slice(0, 1), false);
  const full = span(forecast.rows, true);
  if (!(near > 0) || !(full > near)) return BASE_HEIGHT;
  return Math.min(MAX_HEIGHT, Math.round(BASE_HEIGHT * (full / near)));
}

function DensityConeChart({
  forecast,
  recentPath,
  gammaLevels,
  view,
}: {
  forecast: SpxDensityForecast;
  recentPath: SpxPathPoint[];
  gammaLevels: SpxGammaLevels | null;
  view: ConeView;
}) {
  const hostRef = useRef<HTMLDivElement>(null);
  const height = paneHeight(view, forecast, recentPath);

  useEffect(() => {
    const el = hostRef.current;
    if (!el) return;

    const muted = cssVar("--text-muted", "#8b93a7");
    const borderDim = cssVar("--border-dim", "rgba(148,163,184,0.18)");
    const positive = cssVar("--positive", "#26a69a");
    const negative = cssVar("--negative", "#ef5350");
    const bandBase = cssVar("--positive", "#05ad98");

    const chart = createChart(el, {
      autoSize: true,
      height,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: muted,
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 10,
      },
      grid: {
        vertLines: { color: borderDim, style: LineStyle.Dotted },
        horzLines: { color: borderDim, style: LineStyle.Dotted },
      },
      crosshair: {
        mode: CrosshairMode.Normal,
        vertLine: { color: muted, labelBackgroundColor: borderDim },
        horzLine: { color: muted, labelBackgroundColor: borderDim },
      },
      // The whole point of moving off hand-rolled SVG: real dates on the axis.
      timeScale: {
        borderColor: borderDim,
        timeVisible: false,
        // Blank bar-widths reserved right of the last point. Focused reserves the strip
        // the density silhouette occupies; the fan reserves nothing — its h=5 edge IS
        // the subject and any gap there just reads as dead space. NOT combined with
        // fixRightEdge — that pins the last bar to the frame and silently cancels this
        // offset, which left the profile with zero room and nothing drawn. Scroll/scale
        // are already disabled, so no pinning is needed to keep the content in place.
        rightOffset: view === "focused" ? 3 : 0,
      },
      rightPriceScale: {
        borderColor: borderDim,
        // Headroom above and below the data. Without it lightweight-charts crops
        // hard to the min/max, which makes candle bodies fill most of the pane and
        // forces awkward gridline steps. ~14% each way leaves the price series
        // sitting compactly in the middle with round-number gridlines.
        scaleMargins: { top: 0.14, bottom: 0.14 },
      },
      // Fixed frame: the window is a deliberate composition (14 sessions of context
      // + the 5-day cone), not something to navigate. Interaction is limited to the
      // crosshair.
      handleScroll: false,
      handleScale: false,
    });

    const anchor = forecast.anchor_close;
    const price = (cumReturn: number) => anchor * (1 + cumReturn);

    // ---- price history -------------------------------------------------------
    // vol_index_daily carries close-only rows (index history without OHLC). Those
    // sessions become whitespace: the date stays on the axis, but no candle is
    // fabricated from a close. If NOTHING has OHLC we fall back to a close line so
    // the pane is never blank.
    const complete = recentPath.filter(
      (p) => p.open != null && p.high != null && p.low != null,
    );
    const useCandles = complete.length > 0;
    const series = useCandles
      ? chart.addSeries(CandlestickSeries, {
          upColor: positive,
          downColor: negative,
          borderUpColor: positive,
          borderDownColor: negative,
          wickUpColor: positive,
          wickDownColor: negative,
          priceLineVisible: false,
          lastValueVisible: false,
        })
      : chart.addSeries(LineSeries, {
          color: cssVar("--accent-warm", "#F5A623"),
          lineWidth: 2,
          priceLineVisible: false,
          lastValueVisible: false,
        });

    // Focused = the incoming session only. Carrying all five horizons here stretched
    // the price axis to the h=5 tails (~600 SPX points), which squashed the very
    // next-day density the view exists to show.
    const coneRows =
      view === "focused" ? forecast.rows.slice(0, 1) : forecast.rows;

    const lastBarDate = recentPath.length
      ? recentPath[recentPath.length - 1].date
      : forecast.as_of;
    // Filtered once, here; every series below draws from the survivors. See drawableRows
    // for why a stale or duplicated target date must not reach the axis.
    const drawRows = drawableRows(coneRows, lastBarDate);
    const futureDates = drawRows.map((r) => r.target_date);

    const bars = recentPath.map((p) =>
      useCandles && p.open != null && p.high != null && p.low != null
        ? {
            time: asTime(p.date),
            open: p.open,
            high: p.high,
            low: p.low,
            close: p.close,
          }
        : useCandles
          ? { time: asTime(p.date) }
          : { time: asTime(p.date), value: p.close },
    );
    series.setData([
      ...bars,
      ...futureDates.map((d) => ({ time: asTime(d) })),
    ] as never);

    // ---- the cone ------------------------------------------------------------
    // Band starts pinned at the anchor close so the fan opens from the last real
    // price rather than floating away from it.
    const bandPoints = (
      loKey: keyof SpxDensityHorizon,
      hiKey: keyof SpxDensityHorizon,
    ) => [
      { time: asTime(forecast.as_of), upper: anchor, lower: anchor },
      ...drawRows.map((r) => ({
        time: asTime(r.target_date),
        upper: price(r[hiKey] as number),
        lower: price(r[loKey] as number),
      })),
    ];

    const primitives: Array<BandsIndicator | DensityProfile> = [];
    if (view === "fan") {
      for (const [loKey, hiKey, opacity] of BANDS) {
        const band = new BandsIndicator({
          lineColor: "transparent",
          fillColor: withAlpha(bandBase, opacity),
        });
        series.attachPrimitive(band);
        band.setBandData(bandPoints(loKey, hiKey));
        primitives.push(band);
      }
    } else {
      // Focused: nested probability BLOCKS for the single incoming session, not a
      // widening wedge — over one horizon the interval has constant width, and
      // drawing it as a cone would imply a multi-day spread the model never issued.
      // drawRows, not forecast.rows[0]: if the incoming session's date is already behind
      // the tape there is nothing legitimate to draw at, and the blocks would land on a
      // bar whose outcome is known.
      const head = drawRows[0];
      if (head) {
        for (const [loKey, hiKey, opacity] of BANDS) {
          const block = new BandsIndicator({
            lineColor: "transparent",
            fillColor: withAlpha(bandBase, opacity),
          });
          series.attachPrimitive(block);
          block.setBandData([
            {
              time: asTime(forecast.as_of),
              upper: price(head[hiKey] as number),
              lower: price(head[loKey] as number),
            },
            {
              time: asTime(head.target_date),
              upper: price(head[hiKey] as number),
              lower: price(head[loKey] as number),
            },
          ]);
          primitives.push(block);
        }

        // Flat baseline flush against the price axis, silhouette bulging LEFT into the
        // pane — the volume-profile idiom. Hanging it off the h=1 date and growing
        // right instead put the fat part of the distribution in the corner and left a
        // dead gap against the axis.
        if (head.density) {
          const profile = new DensityProfile({
            upColor: withAlpha(negative, 0.45),
            downColor: withAlpha(positive, 0.45),
            lineColor: withAlpha(muted, 0.7),
            maxWidthPx: 115,
            style: "curve",
            anchor: "pane-right",
            direction: "left",
          });
          series.attachPrimitive(profile);
          profile.setProfile({
            time: asTime(head.target_date), // ignored under anchor: "pane-right"
            bars: densityBarsFromBins(head.density, anchor),
            splitPrice: anchor,
          });
          primitives.push(profile);
        }

        // The two numbers the next-session view is read for, drawn as levels rather
        // than left to the caption underneath. Deliberately not the median: the dotted
        // p50 series already crosses the pane, and a third axis label collides with
        // CALL WALL / γ FLIP, which are the levels that actually constrain a trade.
        for (const [ret, color, title] of [
          [head.q95, negative, "PROJ HIGH"],
          [head.q05, positive, "PROJ LOW"],
        ] as Array<[number, string, string]>) {
          series.createPriceLine({
            price: price(ret),
            color,
            lineWidth: 1,
            lineStyle: LineStyle.Dashed,
            axisLabelVisible: true,
            title,
          });
        }

        // Marks where the cone is issued FROM. Light, not black as in the reference
        // shot: on this theme a black dot disappears whenever the close sits on a wick
        // instead of a candle body.
        const closeDot = chart.addSeries(LineSeries, {
          color: cssVar("--text-primary", "#e2e8f0"),
          lineVisible: false,
          pointMarkersVisible: true,
          pointMarkersRadius: 4,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        closeDot.setData([
          {
            time: asTime(lastBarDate),
            value: recentPath.length
              ? recentPath[recentPath.length - 1].close
              : anchor,
          },
        ] as never);
      }
    }

    // p50 — dotted and faint on purpose. v13 makes no direction claim; drawing it
    // as a solid line would read as a forecast of level, which it is not.
    const median = chart.addSeries(LineSeries, {
      color: muted,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    });
    median.setData([
      { time: asTime(forecast.as_of), value: anchor },
      ...drawRows.map((r) => ({
        time: asTime(r.target_date),
        value: price(r.q50),
      })),
    ] as never);

    // EWMA baseline: outline only, never filled — a yardstick, not a second forecast.
    if (view === "fan") {
      for (const key of ["baseline_q10", "baseline_q90"] as const) {
        const line = chart.addSeries(LineSeries, {
          color: cssVar("--text-secondary", "#94a3b8"),
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          priceLineVisible: false,
          lastValueVisible: false,
          crosshairMarkerVisible: false,
        });
        line.setData([
          { time: asTime(forecast.as_of), value: anchor },
          ...forecast.rows.map((r) => ({
            time: asTime(r.target_date),
            value: price(r[key]),
          })),
        ] as never);
      }
    }

    // ---- dealer levels -------------------------------------------------------
    // Only levels that survived the API-side side-guard arrive here; a wall on the
    // wrong side of spot was already dropped, so nothing needs re-checking.
    if (gammaLevels) {
      const lines: Array<[number | null, string, string]> = [
        [gammaLevels.call_wall, negative, "CALL WALL"],
        [gammaLevels.put_wall, positive, "PUT WALL"],
        [gammaLevels.gamma_flip, cssVar("--accent-vivid", "#c084fc"), "γ FLIP"],
      ];
      for (const [value, color, title] of lines) {
        if (value == null) continue;
        series.createPriceLine({
          price: value,
          color,
          lineWidth: 1,
          lineStyle: LineStyle.Dashed,
          axisLabelVisible: true,
          title,
        });
      }
    }

    chart.timeScale().fitContent();

    return () => {
      for (const p of primitives) series.detachPrimitive(p);
      chart.remove();
    };
  }, [forecast, recentPath, gammaLevels, view, height]);

  return (
    <div
      ref={hostRef}
      data-testid="spx-density-chart"
      style={{ width: "100%", height }}
    />
  );
}

/**
 * The effect below builds the chart from scratch and `chart.remove()`s it on cleanup, so
 * every re-render with new prop IDENTITY costs a full teardown and a visible flash. The
 * panel's poll (`useSyncHook`) calls `setData(json)` unconditionally every 5 minutes, and
 * a fresh JSON parse is never identity-equal — so without this guard an idle page rebuilt
 * the chart twelve times an hour to draw the exact same picture. Comparing the serialised
 * props is honest about what actually matters (the values) and the payload is ~30 bars
 * plus 5 rows, small enough that stringify is cheaper than one wasted rebuild.
 */
export default memo(
  DensityConeChart,
  (a, b) => JSON.stringify(a) === JSON.stringify(b),
);

/** CSS vars in this theme are hex; rgb()/rgba() inputs are passed through with their
 *  own alpha replaced. Anything else is returned untouched rather than mangled. */
function withAlpha(color: string, alpha: number): string {
  const hex = color.trim();
  if (/^#([0-9a-f]{6})$/i.test(hex)) {
    const n = parseInt(hex.slice(1), 16);
    return `rgba(${(n >> 16) & 255}, ${(n >> 8) & 255}, ${n & 255}, ${alpha})`;
  }
  const m = hex.match(/^rgba?\(([^)]+)\)$/i);
  if (m) {
    const [r, g, b] = m[1].split(",").map((s) => s.trim());
    return `rgba(${r}, ${g}, ${b}, ${alpha})`;
  }
  return hex;
}
