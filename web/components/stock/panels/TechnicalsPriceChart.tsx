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
  toBollingerBandData,
  toCandleData,
  toCloseLineData,
  toEmaLineData,
  toSmaLineData,
  toVolumeData,
  type SeriesRow,
} from "@/lib/priceChartData";
import { BandsIndicator } from "@/lib/lwc/bandsIndicator";
import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

const H = 460;

type OverlayMode = "sma" | "ema";
const OVERLAY_MODE_KEY = "technicals:priceOverlayMode";

// ReorderableList.tsx pattern: lazy init + try/catch; client-only component
// so no hydration mismatch.
function loadOverlayMode(): OverlayMode {
  try {
    return localStorage.getItem(OVERLAY_MODE_KEY) === "ema" ? "ema" : "sma";
  } catch {
    return "sma";
  }
}

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
  mas: Record<"fast" | "mid" | "slow", ISeriesApi<"Line">>;
  vwap: ISeriesApi<"Line">;
  bands: BandsIndicator;
};

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

    handlesRef.current = { chart, price, volume, mas, vwap, bands };
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
    const firstAsOf = rows[0]?.as_of ?? "";
    // Indicators are computed over `full` (converged warmup) then sliced to the
    // visible window's left edge.
    const cut = <T extends { time: Time }>(a: T[]): T[] =>
      a.filter((p) => String(p.time) >= firstAsOf);
    if (candleMode) {
      (h.price as ISeriesApi<"Candlestick">).setData(toCandleData(rows));
      h.volume?.setData(
        cut(
          toVolumeData(full, `${positive}59`, `${negative}59`, {
            lowColor: cssVar("--text-muted"),
          }),
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
    // Fit on ticker or window-start change only — a live head append (length
    // change, same first bar) must not reset the user's zoom.
    const fitKey = `${ticker}:${candleMode}:${firstAsOf}`;
    if (fitKey !== fitKeyRef.current) {
      fitKeyRef.current = fitKey;
      h.chart.timeScale().fitContent();
    }
  }, [rows, full, ticker, candleMode, anchor, mode]);

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
      {control}
      <span>{lastBarDate}</span>
    </span>
  );

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
      <Legend mode={mode} showVwap={anchor != null} />
    </AnalyticalSeriesPanel>
  );
}

function Legend({ mode, showVwap }: { mode: OverlayMode; showVwap: boolean }) {
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
    </div>
  );
}
