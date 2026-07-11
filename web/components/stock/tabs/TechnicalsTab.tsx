"use client";

import { useEffect, useRef, useState, type CSSProperties } from "react";
import {
  api,
  type TechnicalsLiveResponse,
  type TechnicalsResponse,
} from "@/lib/api";
import { TechnicalsKpiStrip } from "../panels/TechnicalsKpiStrip";
import { TechnicalsPriceChart } from "../panels/TechnicalsPriceChart";
import { TechnicalsEmptyState } from "../panels/TechnicalsEmptyState";
import {
  TechnicalsKinematicsChart,
  TechnicalsMacdChart,
  TechnicalsRsChart,
  TechnicalsRsiChart,
  TechnicalsVolChart,
  TechnicalsZChart,
} from "../panels/TechnicalsOscillators";
import { ForwardReturnTable } from "../panels/ForwardReturnTable";
import { ReturnHistogram } from "../panels/ReturnHistogram";
import { TechnicalsDetailPanels } from "../panels/TechnicalsDetailPanels";
import { ReorderableList, type ReorderItem } from "../panels/ReorderableList";

type State = {
  ticker: string;
  data: TechnicalsResponse | null;
  error: string | null;
};

export type Timeframe = "full" | "1y" | "ytd" | "3m";

const TIMEFRAME_OPTIONS: { value: Timeframe; label: string }[] = [
  { value: "full", label: "FULL (5Y)" },
  { value: "1y", label: "1Y" },
  { value: "ytd", label: "YTD" },
  { value: "3m", label: "3M" },
];

// Window the daily series to a timeframe. Anchored on the LAST bar's date (not
// wall-clock now) so a stale/weekend payload never yields an empty window. ISO
// date strings compare lexically === chronologically, so the cutoff is a plain
// string >= test — no Date parsing, no timezone. 'full' returns the input as-is.
// ponytail: 3m month-end anchors (e.g. -3mo of the 31st) land on a non-existent
// day and drop a day or two at the boundary — invisible on a chart, not worth
// clamping.
export function sliceSeriesByTimeframe<T extends { as_of?: string | null }>(
  series: T[],
  timeframe: Timeframe,
): T[] {
  if (timeframe === "full" || series.length === 0) return series;
  // Anchor on the last row that actually has a date — not blindly the last row,
  // which could be a spliced head with a null as_of (would else fall back to the
  // unsliced full series and silently ignore the selector).
  let last: string | null | undefined;
  for (let i = series.length - 1; i >= 0; i--) {
    if (series[i]?.as_of) {
      last = series[i]!.as_of;
      break;
    }
  }
  if (!last) return series;
  let cutoff: string;
  if (timeframe === "ytd") {
    cutoff = `${last.slice(0, 4)}-01-01`;
  } else if (timeframe === "1y") {
    // Same day, previous year — MM-DD carried verbatim (no month arithmetic).
    cutoff = `${Number(last.slice(0, 4)) - 1}${last.slice(4)}`;
  } else {
    const [y, m] = last.split("-").map(Number);
    const months = y * 12 + (m - 1) - 3; // 3 calendar months back, in month-space
    const cy = Math.floor(months / 12);
    const cm = (months % 12) + 1;
    cutoff = `${cy}-${String(cm).padStart(2, "0")}-${last.slice(8, 10)}`;
  }
  return series.filter((r) => (r.as_of ?? "") >= cutoff);
}

const TIMEFRAME_TEXT: CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  letterSpacing: 1,
  textTransform: "uppercase",
};

// Custom dropdown, NOT a native <select>: a native option popup can't be themed
// cross-browser, so both the closed control AND the open list are hand-rolled to
// match the Argon terminal look. ponytail: minimal combobox — button + absolutely
// positioned list, outside-click + Escape to close; no arrow-key nav for 4 static
// items (add roving tabindex only if the list grows).
export function TimeframeSelect({
  value,
  onChange,
}: {
  value: Timeframe;
  onChange: (t: Timeframe) => void;
}) {
  const [open, setOpen] = useState(false);
  const ref = useRef<HTMLDivElement>(null);
  const current =
    TIMEFRAME_OPTIONS.find((o) => o.value === value) ?? TIMEFRAME_OPTIONS[0];

  useEffect(() => {
    if (!open) return;
    const onDoc = (e: MouseEvent) => {
      if (ref.current && !ref.current.contains(e.target as Node))
        setOpen(false);
    };
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") setOpen(false);
    };
    document.addEventListener("mousedown", onDoc);
    document.addEventListener("keydown", onKey);
    return () => {
      document.removeEventListener("mousedown", onDoc);
      document.removeEventListener("keydown", onKey);
    };
  }, [open]);

  return (
    <div ref={ref} style={{ position: "relative" }}>
      <button
        type="button"
        aria-haspopup="listbox"
        aria-expanded={open}
        aria-label="Chart timeframe"
        onClick={() => setOpen((o) => !o)}
        style={{
          ...TIMEFRAME_TEXT,
          display: "inline-flex",
          alignItems: "center",
          gap: 6,
          color: "var(--text-secondary)",
          background: "var(--bg-panel-raised)",
          border: "1px solid var(--border-dim)",
          borderRadius: 4,
          padding: "3px 8px",
          cursor: "pointer",
          outline: "none",
        }}
      >
        {current.label}
        <span aria-hidden style={{ fontSize: 7, color: "var(--text-muted)" }}>
          ▼
        </span>
      </button>
      {open && (
        <ul
          role="listbox"
          style={{
            position: "absolute",
            top: "calc(100% + 4px)",
            right: 0,
            margin: 0,
            padding: 4,
            listStyle: "none",
            minWidth: "100%",
            background: "var(--bg-panel-raised)",
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            boxShadow: "0 6px 20px rgba(0, 0, 0, 0.45)",
            zIndex: 30,
          }}
        >
          {TIMEFRAME_OPTIONS.map((o) => {
            const selected = o.value === value;
            return (
              <li
                key={o.value}
                role="option"
                aria-selected={selected}
                onClick={() => {
                  onChange(o.value);
                  setOpen(false);
                }}
                onMouseEnter={(e) => {
                  if (!selected)
                    e.currentTarget.style.background = "var(--bg-hover)";
                }}
                onMouseLeave={(e) => {
                  if (!selected)
                    e.currentTarget.style.background = "transparent";
                }}
                style={{
                  ...TIMEFRAME_TEXT,
                  padding: "4px 10px",
                  borderRadius: 3,
                  cursor: "pointer",
                  whiteSpace: "nowrap",
                  color: selected
                    ? "var(--accent-vivid)"
                    : "var(--text-secondary)",
                  background: selected ? "var(--bg-hover)" : "transparent",
                }}
              >
                {o.label}
              </li>
            );
          })}
        </ul>
      )}
    </div>
  );
}

// Client-side freshness gate — mirrors the server's default
// TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS (900). Beyond this the live head is
// dropped and the EOD daily payload stands.
const LIVE_MAX_AGE_SEC = 900;

function isFresh(live: TechnicalsLiveResponse | null): boolean {
  if (!live?.available || !live.captured_at) return false;
  const age = (Date.now() - new Date(live.captured_at).getTime()) / 1000;
  return Number.isFinite(age) && age <= LIVE_MAX_AGE_SEC;
}

// The live capture's US trading-session date, in ET — NOT the UTC date. A
// capture at e.g. 21:00 ET Friday is already Saturday in UTC, so slicing the
// UTC ISO string (`.slice(0,10)`) would date today's live bar to a non-trading
// Saturday. The ET calendar date keeps it on the real session (Friday) until
// ET midnight. `en-CA` renders YYYY-MM-DD, matching the series' as_of format.
export function etSessionDate(iso: string): string {
  return new Date(iso).toLocaleDateString("en-CA", {
    timeZone: "America/New_York",
  });
}

// Splice the live reading onto the daily payload: append one series row (which
// moves the last point of EVERY oscillator chart — z, RSI, dual MACD, RV,
// kinematics — at once) and override the latest detail readouts that drive the
// per-panel headlines. Sigmoid / forward-returns are intentionally untouched
// (static intraday). Returns the original data unchanged when live is stale.
export function mergeLiveHead(
  data: TechnicalsResponse,
  live: TechnicalsLiveResponse | null,
): TechnicalsResponse {
  if (!isFresh(live) || !live) return data;
  const kin = (live.kinematics ?? {}) as Record<
    string,
    { slope_atr?: number | null }
  >;
  const dm = (live.dual_macd ?? {}) as Record<string, number | null>;
  // isFresh() guarantees captured_at is present.
  // ET trading-session date, NOT the raw ISO slice: on a machine set to a
  // non-ET zone (e.g. HK), captured_at is +08:00, so slicing would date the
  // live bar to the wrong calendar day (Saturday for a Friday session). isFresh
  // guarantees captured_at is present.
  const asOf = etSessionDate(live.captured_at!);
  // When the live job has accumulated today's session OHLC, draw a REAL forming
  // candle (open/high/low/close) instead of a close-only doji that hides on the
  // price line. Guard on the forming candle's own session_date matching today's
  // ET session so a stale row (weekend / after-hours) can't paint yesterday's
  // range onto today; fall back to the close-only spot when it's absent.
  const fo =
    live.forming_ohlc && live.forming_ohlc.session_date === asOf
      ? live.forming_ohlc
      : null;
  const liveRow = {
    as_of: asOf,
    open: fo?.open ?? null,
    high: fo?.high ?? null,
    low: fo?.low ?? null,
    close: fo?.close ?? live.spot ?? null,
    z: live.z ?? null,
    z_band: live.z_band ?? null,
    rsi14: live.rsi14 ?? null,
    rsi_z: live.rsi_z ?? null,
    rv20: live.rv20 ?? null,
    kin_slope20: kin.sma20?.slope_atr ?? null,
    kin_slope50: kin.sma50?.slope_atr ?? null,
    kin_slope200: kin.sma200?.slope_atr ?? null,
    fast_macd_hist_atr: dm.fast_hist ?? null,
    slow_macd_hist_atr: dm.slow_hist ?? null,
  };
  const series = [...(data.series ?? [])];
  // The live reading is TODAY's provisional bar. A SETTLED bar (one carrying
  // real OHLC, open != null) is final — its close/high/low must never be moved
  // by a live tick, even when the capture's UTC date coincides with it (an
  // after-hours capture, or the ET-evening → next-UTC-day date rollover). So:
  // refresh a prior *provisional* head (close-only, open == null) in place;
  // else append a strictly-newer provisional bar; else leave the settled series
  // untouched (the price tile still reflects live via the header path below).
  // This is the "keep the 7/9 EOD bar intact" fix — apex lags a day, so the
  // last EOD bar is a closed prior session, not today's forming candle.
  const last = series[series.length - 1];
  if (last && last.as_of === asOf && last.open == null) {
    series[series.length - 1] = { ...last, ...liveRow };
  } else if (!last?.as_of || asOf > last.as_of) {
    series.push(liveRow as (typeof series)[number]);
  }
  const detail = { ...(data.detail ?? {}) };
  detail.dual_macd = live.dual_macd ?? detail.dual_macd;
  detail.rsi = { ...(detail.rsi ?? {}), rsi14: live.rsi14 };
  detail.distribution = { ...(detail.distribution ?? {}), rv20: live.rv20 };
  // Consume the live spot in the price-card header too: price, z-band, and the
  // 200DMA distance (recomputed off the live spot). Slope / MACD-pctile are
  // EOD-static and left alone.
  const header = { ...(data.header ?? {}) };
  if (live.spot != null) {
    header.price = live.spot;
    if (header.sma200) header.dist_pct = live.spot / header.sma200 - 1;
  }
  if (live.z != null) header.z = live.z;
  if (live.z_band != null) header.z_band = live.z_band;
  if (live.composite != null) header.composite = live.composite;
  // Advance the payload date to the live ET session when the head is newer, so
  // the Price tile reads today's session date (7/10) instead of the stale EOD
  // as_of (7/09) it would otherwise show beside a live price. Only ever forward
  // (lexical ISO compare) — never rewind past a settled EOD date.
  const nextAsOf = !data.as_of || asOf > data.as_of ? asOf : data.as_of;
  return { ...data, as_of: nextAsOf, series, detail, header };
}

export function TechnicalsTab({ ticker }: { ticker: string }) {
  const [state, setState] = useState<State>({
    ticker,
    data: null,
    error: null,
  });
  const [live, setLive] = useState<TechnicalsLiveResponse | null>(null);
  const [timeframe, setTimeframe] = useState<Timeframe>("1y");

  useEffect(() => {
    let cancelled = false;
    api
      .technicals(ticker)
      .then((r) => {
        if (!cancelled) setState({ ticker, data: r, error: null });
      })
      .catch((e) => {
        if (!cancelled) setState({ ticker, data: null, error: String(e) });
      });
    return () => {
      cancelled = true;
    };
  }, [ticker]);

  // Live technicals head — poll every 25s. Never surfaces an error: absent/
  // stale simply keeps the EOD daily payload authoritative.
  useEffect(() => {
    let cancelled = false;
    const poll = () => {
      api
        .technicalsLive(ticker)
        .then((r) => {
          if (!cancelled) setLive(r);
        })
        .catch(() => {
          if (!cancelled) setLive(null);
        });
    };
    poll();
    const id = setInterval(poll, 25_000);
    return () => {
      cancelled = true;
      clearInterval(id);
    };
  }, [ticker]);

  // Auto-fill once per mount+ticker: rows predating migration 105 have null
  // OHLCV, so the price pane can only draw a close line. The per-ticker refresh
  // rewrites the ticker's full history from apex bars (candles + volume). Keyed
  // off the BASE payload — the live head never carries OHLCV, so merging it in
  // would misjudge the gap.
  const autoFilled = useRef<string | null>(null);
  useEffect(() => {
    const base = state.ticker === ticker ? state.data : null;
    if (!base || base.backfill_status !== "ready") return;
    const s = base.series ?? [];
    const last = s[s.length - 1];
    if (!last || last.open != null) return;
    if (autoFilled.current === ticker) return;
    autoFilled.current = ticker;
    api
      .technicalsRefresh(ticker)
      .then((fresh) => {
        setState((cur) =>
          cur.ticker === ticker ? { ticker, data: fresh, error: null } : cur,
        );
      })
      .catch(() => {
        // Non-fatal: the pane degrades to the close line until the next
        // nightly refresh fills OHLCV.
      });
  }, [state, ticker]);

  const ready = state.ticker === ticker;
  const error = ready ? state.error : null;
  const baseData = ready ? state.data : null;
  const liveForTicker = live?.ticker === ticker ? live : null;
  // Full merged payload drives header chrome; the charts below get a windowed
  // view (same rows, sliced by the timeframe selector).
  const data = baseData ? mergeLiveHead(baseData, liveForTicker) : null;

  if (error) {
    return (
      <div style={{ color: "var(--negative)", padding: 16 }}>
        Technicals failed to load: {error}
      </div>
    );
  }
  if (!data) {
    return (
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        Loading technicals…
      </div>
    );
  }
  if (data.backfill_status === "empty") {
    return (
      <TechnicalsEmptyState
        ticker={ticker}
        onComputed={(fresh) => setState({ ticker, data: fresh, error: null })}
      />
    );
  }
  // Windowed view of the daily series — every date-axis chart re-ranges to the
  // selected timeframe. Detail/forward-return panels read latest-only fields, so
  // slicing leaves them unchanged (correct — they're not date-axis graphs).
  const view: TechnicalsResponse = {
    ...data,
    series: sliceSeriesByTimeframe(data.series ?? [], timeframe),
  };

  // The anchor (price) chart is PINNED at the top — it carries the timeframe
  // selector and its date axis is the alignment reference, so it never moves.
  // The oscillator/detail stack below stays reorderable (persisted per-browser).
  const chartItems: ReorderItem[] = [
    { id: "macd", node: <TechnicalsMacdChart data={view} /> },
    { id: "kinematics", node: <TechnicalsKinematicsChart data={view} /> },
    { id: "z", node: <TechnicalsZChart data={view} /> },
    { id: "rsi", node: <TechnicalsRsiChart data={view} /> },
    { id: "vol", node: <TechnicalsVolChart data={view} /> },
    // The return distribution is a shape over its own fixed 60d sample, not a
    // date-axis graph the timeframe should pan — keep it on full data.
    { id: "return-hist", node: <ReturnHistogram data={data} /> },
    { id: "rs", node: <TechnicalsRsChart data={view} /> },
    { id: "forward-returns", node: <ForwardReturnTable data={view} /> },
    { id: "detail", node: <TechnicalsDetailPanels data={view} /> },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      {/* The LIVE/EOD marker lives in the Price tile (see TechnicalsKpiStrip) —
          no separate page-level badge. KPI strip stays on full data. */}
      <TechnicalsKpiStrip
        data={data}
        live={liveForTicker}
        maxAgeSec={LIVE_MAX_AGE_SEC}
      />
      {/* Pinned anchor: timeframe selector sits next to the date; the whole
          stack below re-ranges to it. */}
      <TechnicalsPriceChart
        data={view}
        control={<TimeframeSelect value={timeframe} onChange={setTimeframe} />}
      />
      {/* Aligned stack: oscillators share the anchor's date axis. Drag any row
          to reorder. */}
      {/* key bumped to :v2 so the new macd-first / kinematics-second default
          supersedes any order saved under the original key (the reorder
          feature is <1 day old — no meaningful saved arrangements to preserve). */}
      <ReorderableList
        items={chartItems}
        storageKey="technicals:chartOrder:v2"
      />
    </div>
  );
}
