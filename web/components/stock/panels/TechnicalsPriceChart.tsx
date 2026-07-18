"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  createSeriesMarkers,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type AutoscaleInfo,
  type IChartApi,
  type ISeriesApi,
  type ISeriesMarkersPluginApi,
  type MouseEventParams,
  type SeriesMarker,
  type Time,
} from "lightweight-charts";
import { api, type TechnicalsResponse } from "@/lib/api";
import { fmtDecimal } from "@/lib/formatters";
import { anchoredVwap } from "@/lib/vwap";
import {
  hasOhlcv,
  toBandData,
  toBollingerBandData,
  toCandleData,
  toCloseLineData,
  toEmaLineData,
  toSmaLineData,
  toVolumeData,
  toVolumeMaData,
  type SeriesRow,
} from "@/lib/priceChartData";
import {
  fmtVolCompact,
  highVolMarkers,
  lowVolMarkers,
  volumeMa,
} from "@/lib/indicators";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { ChanlunZhongshu } from "@/lib/lwc/chanlunZhongshu";
import {
  computeChanlunFull,
  type BuySellPoint,
  type ChanlunBar,
  type Zhongshu,
} from "@/lib/chanlun";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

const H = 460;
// Dual-MACD sub-pane rides below price in the SAME chart instance — one shared
// time scale gives locked scroll + pixel-perfect x-alignment for free (v5 panes).
const MACD_H = 150;

type OverlayMode = "sma" | "ema";
const OVERLAY_MODE_KEY = "technicals:priceOverlayMode";
const CHANLUN_KEY = "technicals:chanlun";

// ReorderableList.tsx pattern: lazy init + try/catch; client-only component
// so no hydration mismatch.
function loadOverlayMode(): OverlayMode {
  try {
    return localStorage.getItem(OVERLAY_MODE_KEY) === "ema" ? "ema" : "sma";
  } catch {
    return "sma";
  }
}

function loadChanlun(): boolean {
  try {
    return localStorage.getItem(CHANLUN_KEY) === "1";
  } catch {
    return false;
  }
}

// Canvas needs concrete colors — resolve the Argon CSS variables at mount.
function cssVar(name: string): string {
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
type DualMacdDetail = {
  trend_state?: string;
  tactical_signal?: string;
  confidence?: number | null;
};
// ponytail: color-mix dims a token toward muted — no per-shade CSS var needed.
const dim = (token: string) =>
  `color-mix(in srgb, ${token} 55%, var(--text-muted))`;
export function macdSignal(
  dm: DualMacdDetail | undefined,
): { text: string; color: string } | null {
  if (!dm) return null;
  const hasTactical = !!dm.tactical_signal && dm.tactical_signal !== "NONE";
  const text = hasTactical
    ? `${dm.tactical_signal} · conf ${fmtDecimal(dm.confidence, 2)}`
    : dm.trend_state;
  if (!text) return null;
  const key = (
    hasTactical ? dm.tactical_signal! : dm.trend_state!
  ).toUpperCase();
  const color = /DETERIORATING/.test(key)
    ? dim("var(--positive)") // bull structure, weakening
    : /IMPROVING/.test(key)
      ? dim("var(--negative)") // bear structure, recovering
      : /BULL|DIP_BUY|\bUP\b|LONG/.test(key)
        ? "var(--positive)"
        : /BEAR|RALLY_SELL|DOWN|SHORT/.test(key)
          ? "var(--negative)"
          : "var(--text-muted)";
  return { text, color };
}

// MarketSmith knobs — constants, not UI (trim candidates after live review).
const VOL_MA_PERIOD = 50;
const LOW_VOL_THRESHOLD_PCT = -25;
const TRUNCATE_VOLUME_AT_2X_MA = false; // MarketSmith display style; readout shows true vol

// One readout line for both hover and the default last-bar state: OHLC (or
// close) + volume buzz (V + ×MA50 when an MA value exists for the bar).
function readoutLine(
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

type Anchor = {
  anchorDate: string;
  series: { time: string; value: number }[];
};

function anchorFromServer(
  va: TechnicalsResponse["vwap_anchor"],
): Anchor | null {
  if (!va) return null;
  return {
    anchorDate: va.anchor_date,
    series: (va.series ?? []).map((p) => ({ time: p.as_of, value: p.vwap })),
  };
}

type ChartHandles = {
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
  biSolid: ISeriesApi<"Line">;
  biDashed: ISeriesApi<"Line">;
  clZs: ChanlunZhongshu;
  clMarkers: ISeriesMarkersPluginApi<Time>;
  segSolid: ISeriesApi<"Line">;
  segDashed: ISeriesApi<"Line">;
  segZs: ChanlunZhongshu;
};

const READABLE_BAR_PX = 6; // min bar width before we scroll instead of squish
const RIGHT_GAP_BARS = 10; // gap (in bar-widths) between the last bar and the price axis
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
  if (width > 0 && barCount * READABLE_BAR_PX > width) {
    ts.applyOptions({ barSpacing: READABLE_BAR_PX });
    ts.scrollToPosition(RIGHT_GAP_BARS, false);
  } else {
    // Fit the full short window while explicitly reserving the same right gap.
    ts.setVisibleLogicalRange({ from: 0, to: barCount - 1 + RIGHT_GAP_BARS });
  }
}

export function TechnicalsPriceChart({
  data,
  fullRows,
  control,
}: {
  data: TechnicalsResponse;
  fullRows?: SeriesRow[];
  control?: ReactNode;
}) {
  const rows = useMemo(() => (data.series ?? []) as SeriesRow[], [data.series]);
  // Unwindowed history for client-side indicators (EMA/BB/vol-MA/markers need
  // pre-window warmup); the caller passes the full series, defaulting to the
  // visible rows for back-compat.
  const full = useMemo(() => fullRows ?? rows, [fullRows, rows]);
  const ticker = data.ticker;
  const candleMode = hasOhlcv(rows);
  const [mode, setMode] = useState<OverlayMode>(loadOverlayMode);
  const setModePersist = (m: OverlayMode) => {
    setMode(m);
    try {
      localStorage.setItem(OVERLAY_MODE_KEY, m);
    } catch {
      /* storage unavailable */
    }
  };
  const [chanlunOn, setChanlunOn] = useState<boolean>(loadChanlun);
  const setChanlunPersist = (on: boolean) => {
    setChanlunOn(on);
    try {
      localStorage.setItem(CHANLUN_KEY, on ? "1" : "0");
    } catch {
      /* storage unavailable */
    }
  };
  // Chanlun geometry over the FULL history (window-cut in the data pass, like
  // the other client-side indicators). Pure + deterministic, so memo on rows.
  const chanlunGeo = useMemo(() => {
    if (!chanlunOn || !candleMode) return null;
    const bars: ChanlunBar[] = full.flatMap((r) =>
      r.as_of != null && r.high != null && r.low != null && r.close != null
        ? [{ time: r.as_of, high: r.high, low: r.low, close: r.close }]
        : [],
    );
    return computeChanlunFull(bars);
  }, [full, chanlunOn, candleMode]);

  const containerRef = useRef<HTMLDivElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const handlesRef = useRef<ChartHandles | null>(null);
  // Latest rows for the click/hover callbacks, which are subscribed once per
  // chart build but must see rows appended by the live poll (kept in a ref so
  // a poll append doesn't re-subscribe). Synced in an effect, not in render.
  const rowsRef = useRef<SeriesRow[]>(rows);
  const fitKeyRef = useRef("");
  // as_of → volume MA50 lookup, rebuilt each data pass; read by the hover/leave
  // readout (a ref so the once-subscribed callback sees the latest map).
  const volMaByTimeRef = useRef<Map<string, number>>(new Map());
  // Always-on volume markers (HVE/HV1) vs. the low-vol −NN% labels, which are
  // revealed only for the hovered bar. Refs so the once-subscribed crosshair
  // callback sees the latest sets after a live-poll data pass.
  const baseVolMarkersRef = useRef<SeriesMarker<Time>[]>([]);
  const lowVolByTimeRef = useRef<Map<string, SeriesMarker<Time>>>(new Map());
  const [anchor, setAnchor] = useState<Anchor | null>(() =>
    anchorFromServer(data.vwap_anchor),
  );
  const [err, setErr] = useState<string | null>(null);

  useEffect(() => {
    rowsRef.current = rows;
  }, [rows]);

  // Server anchor is the record of truth whenever a new base payload arrives
  // (ticker switch, refetch, auto-fill): reset the local anchor to it. Run in
  // render — the canonical "adjust state on prop change" pattern, not an
  // effect. The tab preserves this reference across 25s live-head merges, so
  // an optimistic click is not clobbered mid-flight; only a genuine base
  // refetch (new reference) resets it.
  const serverAnchor = data.vwap_anchor;
  const [syncedAnchor, setSyncedAnchor] = useState(serverAnchor);
  if (syncedAnchor !== serverAnchor) {
    setSyncedAnchor(serverAnchor);
    setAnchor(anchorFromServer(serverAnchor));
    setErr(null);
  }

  // Build the chart once per ticker+mode; dispose on change/unmount.
  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const positive = cssVar("--positive");
    const negative = cssVar("--negative");
    const muted = cssVar("--text-muted");
    const borderDim = cssVar("--border-dim");
    const chart = createChart(el, {
      autoSize: true,
      height: H,
      layout: {
        background: { type: ColorType.Solid, color: "transparent" },
        textColor: muted,
        fontFamily: "IBM Plex Mono, monospace",
        fontSize: 10,
        // Sub-pane separator matches the panel chrome; resize disabled so the
        // MACD badge overlay stays anchored to a fixed y.
        panes: { separatorColor: borderDim, enableResize: false },
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
      timeScale: {
        borderColor: borderDim,
        timeVisible: false,
        // Small right-side gap between the last bar and the price axis (in
        // bar-widths). Bars keep a readable minimum width: a long window (FULL)
        // overflows and scrolls horizontally rather than being squished to 1px
        // — the Reset button snaps back to fit-and-latest.
        ...TECHNICALS_TIME_SCALE_OPTIONS,
      },
      rightPriceScale: { borderColor: borderDim },
    });

    const lineOpts = {
      lineWidth: 2 as const,
      priceLineVisible: false,
      lastValueVisible: false,
      crosshairMarkerVisible: false,
    };
    const price = candleMode
      ? chart.addSeries(CandlestickSeries, {
          upColor: positive,
          downColor: negative,
          borderVisible: false,
          wickUpColor: positive,
          wickDownColor: negative,
        })
      : chart.addSeries(LineSeries, {
          color: cssVar("--text-primary"),
          lineWidth: 2,
          // Show the last-price line in close-line mode too (candles get it by
          // default): the marker tracks the merged live head, so this is the
          // "current price" line even before OHLCV backfill lands.
          priceLineVisible: true,
          crosshairMarkerVisible: true,
        });
    // Keep candles clear of the (taller) volume band at the bottom.
    price
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.08, bottom: 0.35 } });

    let volume: ISeriesApi<"Histogram"> | null = null;
    if (candleMode) {
      volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "", // overlay: no left/right axis
        priceLineVisible: false,
        lastValueVisible: false,
        base: 0,
        // Overlay scales autoscale to the data range, which lifts the zero line
        // off the pane floor and leaves the bars floating. Pin the range bottom
        // to 0 so every bar sits ON the floor.
        autoscaleInfoProvider: (orig: () => AutoscaleInfo | null) => {
          const res = orig();
          if (!res?.priceRange) return res;
          return {
            ...res,
            priceRange: { minValue: 0, maxValue: res.priceRange.maxValue },
          };
        },
      });
      volume
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.68, bottom: 0 } });
    }

    // Volume MA + HVE/HV1 & low-vol markers ride the volume overlay scale.
    let volMa: ISeriesApi<"Line"> | null = null;
    let volMarkers: ISeriesMarkersPluginApi<Time> | null = null;
    if (candleMode && volume) {
      volMa = chart.addSeries(LineSeries, {
        color: cssVar("--warning"),
        priceScaleId: "", // same overlay scale as the volume histogram
        lineWidth: 1,
        priceLineVisible: false,
        lastValueVisible: false,
        crosshairMarkerVisible: false,
      });
      volMa
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.68, bottom: 0 } });
      volMarkers = createSeriesMarkers(volume, [], VOLUME_MARKER_OPTIONS);
    }

    // Three MA lines, refilled per mode (SMA20/50/200 or EMA5/20/50). Same
    // colors/weights in both modes — fast → --accent-warm, mid → --accent-vol,
    // slow → --accent-vivid.
    const mas = {
      fast: chart.addSeries(LineSeries, {
        color: cssVar("--accent-warm"),
        ...lineOpts,
      }),
      mid: chart.addSeries(LineSeries, {
        color: cssVar("--accent-vol"),
        ...lineOpts,
      }),
      slow: chart.addSeries(LineSeries, {
        color: cssVar("--accent-vivid"),
        ...lineOpts,
      }),
    };
    const vwap = chart.addSeries(LineSeries, {
      color: cssVar("--accent-cool"),
      lineStyle: LineStyle.Dashed,
      ...lineOpts,
      lineWidth: 3, // thicker than the SMAs — anchored VWAP is the focal line
    });
    const bands = new BandsIndicator({
      lineColor: "transparent",
      fillColor: `${cssVar("--accent-bg")}1a`, // ~10% alpha, matches the SVG envelope
      lineWidth: 1,
    });
    price.attachPrimitive(bands);

    // Chanlun overlay: 笔 polylines (solid confirmed / dashed provisional
    // tail), 中枢 rectangles (custom primitive), 买卖点 markers on the price
    // series (the volume markers own the volume series). Created always, fed
    // empty data while the toggle is off — the toggle must not rebuild the
    // chart.
    const clColor = cssVar("--text-secondary");
    const biLineOpts = { ...lineOpts, lineWidth: 1 as const };
    const biSolid = chart.addSeries(LineSeries, {
      color: clColor,
      ...biLineOpts,
    });
    const biDashed = chart.addSeries(LineSeries, {
      color: clColor,
      lineStyle: LineStyle.Dashed,
      ...biLineOpts,
    });
    const clZs = new ChanlunZhongshu({
      fillColor: `${cssVar("--accent-cool")}14`, // ~8% alpha fill
      borderColor: `${cssVar("--accent-cool")}80`,
    });
    price.attachPrimitive(clZs);
    const clMarkers = createSeriesMarkers(price, []);

    // 线段 layer: thicker amber polylines + a second zhongshu-primitive
    // instance for 段级中枢 (the primitive takes per-instance options; it is
    // deliberately NOT edited — spec §2).
    const segColor = cssVar("--accent-warm");
    const segSolid = chart.addSeries(LineSeries, {
      color: segColor,
      ...lineOpts, // lineWidth 2 — deliberately thicker than the 笔 lines
    });
    const segDashed = chart.addSeries(LineSeries, {
      color: segColor,
      lineStyle: LineStyle.Dashed,
      ...lineOpts,
    });
    const segZs = new ChanlunZhongshu({
      fillColor: `${segColor}10`, // ~6% alpha — fainter than the 笔级 fill
      borderColor: `${segColor}66`,
    });
    price.attachPrimitive(segZs);

    // Dual MACD in pane index 1 (below price). Two histograms sharing one price
    // scale: the slow 55/89/34 is the structural background (accent-vol, ~50%
    // alpha) drawn first; the fast 13/21/9 is the sharp tactical bar on top, its
    // per-bar color green/red by sign. LWC histograms are full-column width, so
    // z-order + alpha (not the SVG's nested widths) separates the two.
    const macdSlow = chart.addSeries(
      HistogramSeries,
      {
        color: `${cssVar("--accent-vol")}80`,
        base: 0,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    );
    const macdFast = chart.addSeries(
      HistogramSeries,
      {
        color: positive, // overridden per-bar in setData
        base: 0,
        priceLineVisible: false,
        lastValueVisible: false,
      },
      1,
    );
    // Both MACD series share pane 1's right scale — tighten its margins.
    macdFast
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.12, bottom: 0.12 } });
    // Zero reference line — LWC histograms draw no axis, so a faint dotted 0
    // restores the "how far from zero / where's the crossing" read.
    macdSlow.createPriceLine({
      price: 0,
      color: borderDim,
      lineWidth: 1,
      lineStyle: LineStyle.Dotted,
      axisLabelVisible: false,
    });
    // Ratio split: price pane keeps ~H, MACD rides a short ~MACD_H pane below.
    const panes = chart.panes();
    panes[0]?.setStretchFactor(H);
    panes[1]?.setStretchFactor(MACD_H);

    handlesRef.current = {
      chart,
      price,
      volume,
      mas,
      vwap,
      bands,
      volMa,
      volMarkers,
      macdSlow,
      macdFast,
      biSolid,
      biDashed,
      clZs,
      clMarkers,
      segSolid,
      segDashed,
      segZs,
    };
    fitKeyRef.current = ""; // force a fitContent on the first data pass

    // Click-to-anchor VWAP (candle mode only — needs H/L/C + volume).
    const onClick = (param: MouseEventParams<Time>) => {
      if (!candleMode) return;
      if (!param.point || param.time === undefined) return;
      const t = String(param.time);
      const local = anchoredVwap(rowsRef.current, t);
      if (local.length === 0) return;
      setErr(null);
      setAnchor({ anchorDate: t, series: local }); // optimistic
      api
        .vwapAnchorSet(ticker, { anchor_date: t })
        .then((resp) =>
          setAnchor({
            anchorDate: resp.anchor_date,
            series: (resp.series ?? []).map((p) => ({
              time: p.as_of,
              value: p.vwap,
            })),
          }),
        )
        .catch((e) => setErr(`VWAP anchor not saved: ${String(e)}`));
    };
    chart.subscribeClick(onClick);

    // Hover readout (date · OHLC · volume · ×MA50) — direct DOM write. Volume
    // is read from rowsRef (the TRUE value), never the possibly-truncated
    // histogram. Crosshair-leave restores the last-bar line, not empty.
    const restoreLastReadout = () => {
      const out = readoutRef.current;
      if (!out) return;
      const last = rowsRef.current[rowsRef.current.length - 1];
      out.textContent = last?.as_of
        ? readoutLine(
            last.as_of,
            {
              open: last.open ?? undefined,
              high: last.high ?? undefined,
              low: last.low ?? undefined,
              close: last.close ?? undefined,
              value: last.close ?? undefined,
            },
            last.volume,
            volMaByTimeRef.current.get(last.as_of),
          )
        : "";
    };
    // Low-vol −NN% labels are hidden by default; reveal only the hovered bar's,
    // merged into the always-on HVE/HV1 base. Diffed against the last shown bar
    // so setMarkers doesn't fire on every crosshair pixel move.
    let lastLowTime: string | null = null;
    const setHoverMarkers = (t: string | null) => {
      if (!volMarkers) return;
      const key = t && lowVolByTimeRef.current.has(t) ? t : null;
      if (key === lastLowTime) return;
      lastLowTime = key;
      if (!key) {
        volMarkers.setMarkers(baseVolMarkersRef.current);
        return;
      }
      const low = lowVolByTimeRef.current.get(key) as SeriesMarker<Time>;
      volMarkers.setMarkers(
        [...baseVolMarkersRef.current, low].sort((a, b) =>
          String(a.time).localeCompare(String(b.time)),
        ),
      );
    };
    const onMove = (param: MouseEventParams<Time>) => {
      const out = readoutRef.current;
      if (!out) return;
      if (!param.point || param.time === undefined) {
        restoreLastReadout();
        setHoverMarkers(null);
        return;
      }
      const bar = param.seriesData.get(price) as
        | {
            open?: number;
            high?: number;
            low?: number;
            close?: number;
            value?: number;
          }
        | undefined;
      if (!bar) {
        restoreLastReadout();
        setHoverMarkers(null);
        return;
      }
      const t = String(param.time);
      const row = rowsRef.current.find((r) => r.as_of === t);
      out.textContent = readoutLine(
        t,
        bar,
        row?.volume,
        volMaByTimeRef.current.get(t),
      );
      setHoverMarkers(t);
    };
    chart.subscribeCrosshairMove(onMove);

    return () => {
      chart.unsubscribeClick(onClick);
      chart.unsubscribeCrosshairMove(onMove);
      chart.remove();
      handlesRef.current = null;
    };
  }, [ticker, candleMode]);

  // Data pass: setData on every change; fit only when the window/ticker moves.
  useEffect(() => {
    const h = handlesRef.current;
    if (!h) return;
    const positive = cssVar("--positive");
    const negative = cssVar("--negative");
    const firstAsOf = rows[0]?.as_of ?? "";
    // Indicators are computed over `full` (converged warmup) then sliced to the
    // visible window's left edge.
    const cut = <T extends { time: Time }>(a: T[]): T[] =>
      a.filter((p) => String(p.time) >= firstAsOf);
    if (candleMode) {
      (h.price as ISeriesApi<"Candlestick">).setData(toCandleData(rows));
      const volMaFull = volumeMa(
        full.map((r) => r.volume),
        VOL_MA_PERIOD,
      );
      h.volume?.setData(
        cut(
          toVolumeData(full, positive, negative, {
            // Every bar keeps its up/down hue; magnitude alone drives intensity
            // (no separate gray "lowest-in-window" category — it muddied the
            // quiet bars once the buzz opacity was also applied).
            magnitude: volMaFull, // opacity scales with volume/MA (buzz)
            truncateAt: TRUNCATE_VOLUME_AT_2X_MA
              ? volMaFull.map((m) => (m == null ? null : 2 * m))
              : undefined,
          }),
        ),
      );
      h.volMa?.setData(cut(toVolumeMaData(full, VOL_MA_PERIOD)));
      if (h.volMarkers) {
        // HVE/HV1 stay pinned; the low-vol −NN% labels move to a by-time map so
        // onMove can reveal just the hovered bar's (they overlap illegibly when
        // all shown at once).
        const base = highVolMarkers(full, { color: cssVar("--text-secondary") })
          .filter((m) => m.time >= firstAsOf)
          .sort((a, b) => (a.time < b.time ? -1 : a.time > b.time ? 1 : 0))
          .map((m) => ({ ...m, time: m.time as Time }));
        baseVolMarkersRef.current = base;
        lowVolByTimeRef.current = new Map(
          lowVolMarkers(full, volMaFull, {
            thresholdPct: LOW_VOL_THRESHOLD_PCT,
            // Bright text — this label is revealed one-at-a-time on hover, so it
            // must read clearly; --text-muted was invisible on the dark pane.
            color: cssVar("--text-primary"),
          })
            .filter((m) => m.time >= firstAsOf)
            .map((m) => [m.time, { ...m, time: m.time as Time }]),
        );
        h.volMarkers.setMarkers(base);
      }
      volMaByTimeRef.current = new Map(
        full.flatMap((r, i) =>
          volMaFull[i] != null && r.as_of
            ? [[r.as_of, volMaFull[i] as number] as [string, number]]
            : [],
        ),
      );
    } else {
      (h.price as ISeriesApi<"Line">).setData(toCloseLineData(rows));
    }
    if (mode === "sma") {
      h.mas.fast.setData(toSmaLineData(rows, "sma20"));
      h.mas.mid.setData(toSmaLineData(rows, "sma50"));
      h.mas.slow.setData(toSmaLineData(rows, "sma200"));
      h.bands.setBandData(toBandData(rows));
    } else {
      h.mas.fast.setData(cut(toEmaLineData(full, 5)));
      h.mas.mid.setData(cut(toEmaLineData(full, 20)));
      h.mas.slow.setData(cut(toEmaLineData(full, 50)));
      h.bands.setBandData(cut(toBollingerBandData(full)));
    }
    const visVwap = anchor
      ? anchor.series.filter((p) => p.time >= firstAsOf)
      : [];
    h.vwap.setData(
      visVwap.map((p) => ({ time: p.time as Time, value: p.value })),
    );
    // Dual MACD sub-pane. Slow drawn first (structural background), fast on top
    // colored by sign. Both share the visible window so their bars line up with
    // the candles above them (one time scale).
    h.macdSlow.setData(
      rows.flatMap((r) =>
        r.as_of != null && r.slow_macd_hist_atr != null
          ? [{ time: r.as_of as Time, value: r.slow_macd_hist_atr }]
          : [],
      ),
    );
    h.macdFast.setData(
      rows.flatMap((r) =>
        r.as_of != null && r.fast_macd_hist_atr != null
          ? [
              {
                time: r.as_of as Time,
                value: r.fast_macd_hist_atr,
                color: r.fast_macd_hist_atr >= 0 ? positive : negative,
              },
            ]
          : [],
      ),
    );
    // Chanlun overlay: geometry precomputed over `full`, cut to the window
    // here. The dashed tail restarts at the last confirmed vertex so the two
    // polylines connect.
    if (chanlunGeo) {
      const polyline = (
        vs: { time: string; price: number; confirmed: boolean }[],
        solidSeries: ISeriesApi<"Line">,
        dashedSeries: ISeriesApi<"Line">,
      ) => {
        const firstProv = vs.findIndex((v) => !v.confirmed);
        const solid = firstProv === -1 ? vs : vs.slice(0, firstProv);
        const dashed =
          firstProv === -1 ? [] : vs.slice(Math.max(0, firstProv - 1));
        solidSeries.setData(
          solid.map((v) => ({ time: v.time as Time, value: v.price })),
        );
        dashedSeries.setData(
          dashed.map((v) => ({ time: v.time as Time, value: v.price })),
        );
      };
      polyline(
        chanlunGeo.vertices.filter((v) => v.time >= firstAsOf),
        h.biSolid,
        h.biDashed,
      );
      polyline(
        chanlunGeo.segVertices.filter((v) => v.time >= firstAsOf),
        h.segSolid,
        h.segDashed,
      );
      const rects = (zs: Zhongshu[]) =>
        zs
          .filter((z) => z.end >= firstAsOf)
          .map((z) => ({
            start: (z.start >= firstAsOf ? z.start : firstAsOf) as Time,
            end: z.end as Time,
            zg: z.zg,
            zd: z.zd,
            confirmed: z.confirmed,
          }));
      h.clZs.setRects(rects(chanlunGeo.zhongshus));
      h.segZs.setRects(rects(chanlunGeo.segZhongshus));
      const marker = (p: BuySellPoint, prefix: string, size: number) => {
        const buy = p.kind.endsWith("B");
        return {
          time: p.time as Time,
          position: buy ? ("belowBar" as const) : ("aboveBar" as const),
          shape: buy ? ("arrowUp" as const) : ("arrowDown" as const),
          color: buy ? positive : negative,
          text: `${prefix}${p.kind}${p.confirmed ? "" : "?"}${p.resonant ? "★" : ""}`,
          size,
        };
      };
      const divColor = cssVar("--accent-warm");
      h.clMarkers.setMarkers(
        [
          ...chanlunGeo.points
            .filter((p) => p.time >= firstAsOf)
            .map((p) => marker(p, "", 1)),
          ...chanlunGeo.segPoints
            .filter((p) => p.time >= firstAsOf)
            .map((p) => marker(p, "段", 2)),
          ...chanlunGeo.divergences
            .filter((d) => d.time >= firstAsOf)
            .map((d) => ({
              time: d.time as Time,
              position:
                d.kind === "top"
                  ? ("aboveBar" as const)
                  : ("belowBar" as const),
              shape: "circle" as const,
              color: divColor,
              text: `${d.kind === "top" ? "顶背离" : "底背离"}${d.confirmed ? "" : "?"}`,
              size: 1,
            })),
        ].sort((a, b) => String(a.time).localeCompare(String(b.time))),
      );
    } else {
      h.biSolid.setData([]);
      h.biDashed.setData([]);
      h.segSolid.setData([]);
      h.segDashed.setData([]);
      h.clZs.setRects([]);
      h.segZs.setRects([]);
      h.clMarkers.setMarkers([]);
    }
    // Fit on ticker or window-start change only — a live head append (length
    // change, same first bar) must not reset the user's zoom.
    const fitKey = `${ticker}:${candleMode}:${firstAsOf}`;
    if (fitKey !== fitKeyRef.current) {
      fitKeyRef.current = fitKey;
      resetView(h, rows.length);
    }
    // Default (no hover) readout: the last bar's line with buzz.
    const lastRow = rows[rows.length - 1];
    if (readoutRef.current && lastRow?.as_of) {
      readoutRef.current.textContent = readoutLine(
        lastRow.as_of,
        {
          open: lastRow.open ?? undefined,
          high: lastRow.high ?? undefined,
          low: lastRow.low ?? undefined,
          close: lastRow.close ?? undefined,
          value: lastRow.close ?? undefined,
        },
        lastRow.volume,
        volMaByTimeRef.current.get(lastRow.as_of),
      );
    }
  }, [rows, full, ticker, candleMode, anchor, mode, chanlunGeo]);

  const clearAnchor = () => {
    setAnchor(null);
    setErr(null);
    api
      .vwapAnchorClear(ticker)
      .catch((e) => setErr(`VWAP clear failed: ${String(e)}`));
  };

  // Date shown = the newest bar actually plotted, NOT data.as_of. apex only
  // carries EOD bars through the previous business day, so during RTH the live
  // head appends today's forming bar — the label must follow it to today rather
  // than pin to the stale apex date. Falls back to as_of if the series is empty.
  const lastBarDate = rows[rows.length - 1]?.as_of ?? data.as_of ?? "";

  const header: ReactNode = (
    <span
      data-testid="technicals-chart-controls"
      style={{
        display: "inline-flex",
        flexWrap: "wrap",
        justifyContent: "flex-end",
        alignItems: "center",
        gap: 10,
        maxWidth: "100%",
      }}
    >
      {anchor && (
        <button
          type="button"
          onClick={clearAnchor}
          title="Clear anchored VWAP"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1,
            color: "var(--text-secondary)",
            background: "var(--bg-panel-raised)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: "2px 7px",
            cursor: "pointer",
          }}
        >
          VWAP ⚓ {anchor.anchorDate} ✕
        </button>
      )}
      <span
        role="group"
        aria-label="Overlay mode"
        style={{ display: "inline-flex", gap: 0 }}
      >
        {(
          [
            ["sma", "SMA·σ"],
            ["ema", "EMA·BB"],
          ] as const
        ).map(([m, label]) => (
          <button
            key={m}
            type="button"
            onClick={() => setModePersist(m)}
            aria-pressed={mode === m}
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              letterSpacing: 1,
              color: mode === m ? "var(--text-primary)" : "var(--text-muted)",
              background: mode === m ? "var(--bg-panel-raised)" : "transparent",
              border: "1px solid var(--border-dim)",
              borderRadius: m === "sma" ? "4px 0 0 4px" : "0 4px 4px 0",
              marginLeft: m === "ema" ? -1 : 0,
              padding: "2px 7px",
              cursor: "pointer",
            }}
          >
            {label}
          </button>
        ))}
      </span>
      {candleMode && (
        <button
          type="button"
          onClick={() => setChanlunPersist(!chanlunOn)}
          aria-pressed={chanlunOn}
          data-testid="chanlun-toggle"
          title="Zen overlay — 笔 · 中枢 · 买卖点"
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1,
            color: chanlunOn ? "var(--text-primary)" : "var(--text-muted)",
            background: chanlunOn ? "var(--bg-panel-raised)" : "transparent",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: "2px 7px",
            cursor: "pointer",
          }}
        >
          Zen
        </button>
      )}
      <button
        type="button"
        aria-label="Reset zoom and jump to latest bar"
        onClick={() => {
          const h = handlesRef.current;
          if (h) resetView(h, rows.length);
        }}
        title="Reset zoom — fit and jump to the latest bar"
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1,
          color: "var(--text-muted)",
          background: "transparent",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          padding: "2px 7px",
          cursor: "pointer",
        }}
      >
        ⟲ RESET
      </button>
      {control}
      <span>{lastBarDate}</span>
    </span>
  );

  const macd = macdSignal(data.detail?.dual_macd as DualMacdDetail | undefined);

  const title =
    mode === "sma"
      ? "Price, Moving Averages & ±1.5σ Band"
      : "Price, EMAs & Bollinger Bands";

  if (rows.length < 2) {
    return (
      <AnalyticalSeriesPanel title={title} subtitle="anchor" headline={header}>
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough history.
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  return (
    <AnalyticalSeriesPanel
      title={title}
      subtitle={
        candleMode
          ? "candles · volume · click a bar to anchor VWAP"
          : "close line · candles arrive after the next refresh"
      }
      headline={header}
    >
      <div style={{ position: "relative" }}>
        <div
          ref={containerRef}
          data-testid="technicals-price-chart"
          data-volume-ma={candleMode ? VOL_MA_PERIOD : undefined}
          style={{ width: "100%", height: H + MACD_H }}
        />
        <div
          ref={readoutRef}
          style={{
            position: "absolute",
            top: 4,
            left: 8,
            right: 8,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-secondary)",
            pointerEvents: "none",
            whiteSpace: "normal",
            overflowWrap: "anywhere",
          }}
        />
      </div>
      {err && (
        <div style={{ color: "var(--negative)", fontSize: 11, marginTop: 6 }}>
          {err}
        </div>
      )}
      <Legend
        mode={mode}
        showVwap={anchor != null}
        showChanlun={chanlunOn && candleMode}
      />
      {chanlunOn && candleMode && (
        <div
          style={{
            fontSize: 11,
            color: "var(--text-muted)",
            marginTop: 6,
            lineHeight: 1.55,
          }}
        >
          Zen: gray polyline = 笔 (dashed tail = still forming), boxes = 中枢
          [ZD, ZG] (dashed border = extending), markers = 买卖点 — green
          1B/2B/3B buys, red 1S/2S/3S sells, &quot;?&quot; = provisional and may
          be erased. 1st class = trend + MACD-area 背驰; 3rd class = pullback
          holds outside the 中枢. Amber dots = 顶背离/底背离 (new extreme vs the
          prior same-direction 笔 on weaker MACD area — annotation, not a
          signal). Structures on the trailing edge repaint by design — decisions
          belong on confirmed marks only. Amber thick lines = 线段 (segments)
          with amber 段级中枢 boxes; 段-prefixed markers = segment-level 买卖点;
          ★ = weekly×daily 区间套 resonance (both levels confirmed).
        </div>
      )}
      <MacdLegend signal={macd} />
      <div
        style={{
          fontSize: 11,
          color: "var(--text-muted)",
          marginTop: 8,
          lineHeight: 1.55,
        }}
      >
        Two MACD histograms on one ATR-normalized scale: the wide muted bars are
        the slow 55/89/34 (structural trend); the sharp bars are the fast
        13/21/9 (tactical timing). When the slow trend is up but the fast bars
        dip below zero and start curling back up, that&apos;s a DIP_BUY (mirror
        = RALLY_SELL). The badge shows the current tactical signal, its
        confidence, and the trend/momentum-balance state.
      </div>
    </AnalyticalSeriesPanel>
  );
}

function Legend({
  mode,
  showVwap,
  showChanlun,
}: {
  mode: OverlayMode;
  showVwap: boolean;
  showChanlun: boolean;
}) {
  const item = (color: string, label: string) => (
    <span
      key={label}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        marginRight: 12,
      }}
    >
      <span
        style={{
          width: 12,
          height: 2,
          background: color,
          display: "inline-block",
        }}
      />
      <span style={{ fontSize: 10, color: "var(--text-muted)" }}>{label}</span>
    </span>
  );
  const labels =
    mode === "sma"
      ? (["SMA20", "SMA50", "SMA200"] as const)
      : (["EMA5", "EMA20", "EMA50"] as const);
  return (
    <div style={{ marginTop: 6 }}>
      {item("var(--text-primary)", "PRICE")}
      {item("var(--accent-warm)", labels[0])}
      {item("var(--accent-vol)", labels[1])}
      {item("var(--accent-vivid)", labels[2])}
      {showVwap && item("var(--accent-cool)", "VWAP ⚓")}
      {showChanlun && item("var(--text-secondary)", "Zen 笔·中枢·买卖点")}
      {showChanlun && item("var(--accent-warm)", "线段·段级中枢")}
    </div>
  );
}

// MACD sub-pane legend: wide muted slow (structural) + split green/red fast
// (tactical), with the directional signal badge right-aligned. Mirrors the
// retired OscillatorChart swatches.
export function MacdLegend({
  signal,
}: {
  signal: { text: string; color: string } | null;
}) {
  return (
    <div
      style={{
        marginTop: 4,
        display: "flex",
        gap: 16,
        alignItems: "center",
      }}
    >
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <span
          style={{
            width: 14,
            height: 9,
            background: "var(--accent-vol)",
            opacity: 0.5,
            display: "inline-block",
            borderRadius: 1,
          }}
        />
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          SLOW 55/89/34 · structural
        </span>
      </span>
      <span style={{ display: "inline-flex", alignItems: "center", gap: 5 }}>
        <span
          style={{ display: "inline-flex", width: 8, height: 9 }}
          aria-hidden
        >
          <span style={{ flex: 1, background: "var(--positive)" }} />
          <span style={{ flex: 1, background: "var(--negative)" }} />
        </span>
        <span style={{ fontSize: 10, color: "var(--text-muted)" }}>
          FAST 13/21/9 · tactical
        </span>
      </span>
      {signal && (
        <span
          data-testid="technicals-macd-signal"
          style={{
            marginLeft: "auto",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: 1,
            fontWeight: 700,
            color: signal.color,
          }}
        >
          {signal.text.toUpperCase()}
        </span>
      )}
    </div>
  );
}
