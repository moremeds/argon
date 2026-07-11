"use client";

import { useEffect, useMemo, useRef, useState, type ReactNode } from "react";
import {
  CandlestickSeries,
  ColorType,
  createChart,
  CrosshairMode,
  HistogramSeries,
  LineSeries,
  LineStyle,
  type IChartApi,
  type ISeriesApi,
  type MouseEventParams,
  type Time,
} from "lightweight-charts";
import { api, type TechnicalsResponse } from "@/lib/api";
import { anchoredVwap } from "@/lib/vwap";
import {
  hasOhlcv,
  toBandData,
  toCandleData,
  toCloseLineData,
  toSmaLineData,
  toVolumeData,
  type SeriesRow,
} from "@/lib/priceChartData";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

const H = 460;

// Canvas needs concrete colors — resolve the Argon CSS variables at mount.
function cssVar(name: string): string {
  const v = getComputedStyle(document.documentElement)
    .getPropertyValue(name)
    .trim();
  return v || "#888888";
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
  smas: Record<"sma20" | "sma50" | "sma200", ISeriesApi<"Line">>;
  vwap: ISeriesApi<"Line">;
  bands: BandsIndicator;
};

export function TechnicalsPriceChart({
  data,
  control,
}: {
  data: TechnicalsResponse;
  control?: ReactNode;
}) {
  const rows = useMemo(() => (data.series ?? []) as SeriesRow[], [data.series]);
  const ticker = data.ticker;
  const candleMode = hasOhlcv(rows);

  const containerRef = useRef<HTMLDivElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const handlesRef = useRef<ChartHandles | null>(null);
  // Latest rows for the click/hover callbacks, which are subscribed once per
  // chart build but must see rows appended by the live poll (kept in a ref so
  // a poll append doesn't re-subscribe). Synced in an effect, not in render.
  const rowsRef = useRef<SeriesRow[]>(rows);
  const fitKeyRef = useRef("");
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
      timeScale: { borderColor: borderDim, timeVisible: false },
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
    // Keep candles clear of the volume band at the bottom.
    price
      .priceScale()
      .applyOptions({ scaleMargins: { top: 0.08, bottom: 0.25 } });

    let volume: ISeriesApi<"Histogram"> | null = null;
    if (candleMode) {
      volume = chart.addSeries(HistogramSeries, {
        priceFormat: { type: "volume" },
        priceScaleId: "", // overlay: no left/right axis
        priceLineVisible: false,
        lastValueVisible: false,
      });
      volume
        .priceScale()
        .applyOptions({ scaleMargins: { top: 0.78, bottom: 0 } });
    }

    const smas = {
      sma20: chart.addSeries(LineSeries, {
        color: cssVar("--accent-warm"),
        ...lineOpts,
      }),
      sma50: chart.addSeries(LineSeries, {
        color: cssVar("--accent-vol"),
        ...lineOpts,
      }),
      sma200: chart.addSeries(LineSeries, {
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

    handlesRef.current = { chart, price, volume, smas, vwap, bands };
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

    // Hover readout (date · OHLC · volume) — direct DOM write, no re-render.
    const onMove = (param: MouseEventParams<Time>) => {
      const out = readoutRef.current;
      if (!out) return;
      if (!param.point || param.time === undefined) {
        out.textContent = "";
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
      const vol = volume
        ? (param.seriesData.get(volume) as { value?: number } | undefined)
        : undefined;
      if (!bar) {
        out.textContent = "";
        return;
      }
      const f = (x?: number) => (x == null ? "–" : x.toFixed(2));
      out.textContent =
        bar.open != null
          ? `${param.time}  O ${f(bar.open)} H ${f(bar.high)} L ${f(bar.low)} C ${f(bar.close)}` +
            (vol?.value != null
              ? `  V ${Intl.NumberFormat("en-US").format(vol.value)}`
              : "")
          : `${param.time}  C ${f(bar.value)}`;
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
    if (candleMode) {
      (h.price as ISeriesApi<"Candlestick">).setData(toCandleData(rows));
      h.volume?.setData(toVolumeData(rows, `${positive}59`, `${negative}59`));
    } else {
      (h.price as ISeriesApi<"Line">).setData(toCloseLineData(rows));
    }
    h.smas.sma20.setData(toSmaLineData(rows, "sma20"));
    h.smas.sma50.setData(toSmaLineData(rows, "sma50"));
    h.smas.sma200.setData(toSmaLineData(rows, "sma200"));
    h.bands.setBandData(toBandData(rows));
    const firstAsOf = rows[0]?.as_of ?? "";
    const visVwap = anchor
      ? anchor.series.filter((p) => p.time >= firstAsOf)
      : [];
    h.vwap.setData(
      visVwap.map((p) => ({ time: p.time as Time, value: p.value })),
    );
    // Fit on ticker or window-start change only — a live head append (length
    // change, same first bar) must not reset the user's zoom.
    const fitKey = `${ticker}:${candleMode}:${firstAsOf}`;
    if (fitKey !== fitKeyRef.current) {
      fitKeyRef.current = fitKey;
      h.chart.timeScale().fitContent();
    }
  }, [rows, ticker, candleMode, anchor]);

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
    <span style={{ display: "inline-flex", alignItems: "center", gap: 10 }}>
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
      {control}
      <span>{lastBarDate}</span>
    </span>
  );

  if (rows.length < 2) {
    return (
      <AnalyticalSeriesPanel
        title="Price, Moving Averages & ±1.5σ Band"
        subtitle="anchor"
        headline={header}
      >
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>
          Not enough history.
        </div>
      </AnalyticalSeriesPanel>
    );
  }

  return (
    <AnalyticalSeriesPanel
      title="Price, Moving Averages & ±1.5σ Band"
      subtitle={
        candleMode
          ? "candles · volume · click a bar to anchor VWAP"
          : "close line · candles arrive after the next refresh"
      }
      headline={header}
    >
      <div style={{ position: "relative" }}>
        <div ref={containerRef} style={{ width: "100%", height: H }} />
        <div
          ref={readoutRef}
          style={{
            position: "absolute",
            top: 4,
            left: 8,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-secondary)",
            pointerEvents: "none",
            whiteSpace: "pre",
          }}
        />
      </div>
      {err && (
        <div style={{ color: "var(--negative)", fontSize: 11, marginTop: 6 }}>
          {err}
        </div>
      )}
      <Legend showVwap={anchor != null} />
    </AnalyticalSeriesPanel>
  );
}

function Legend({ showVwap }: { showVwap: boolean }) {
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
  return (
    <div style={{ marginTop: 6 }}>
      {item("var(--text-primary)", "PRICE")}
      {item("var(--accent-warm)", "SMA20")}
      {item("var(--accent-vol)", "SMA50")}
      {item("var(--accent-vivid)", "SMA200")}
      {showVwap && item("var(--accent-cool)", "VWAP ⚓")}
    </div>
  );
}
