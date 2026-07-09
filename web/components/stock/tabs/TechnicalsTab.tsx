"use client";

import { useEffect, useState } from "react";
import {
  api,
  type TechnicalsLiveResponse,
  type TechnicalsResponse,
} from "@/lib/api";
import { TechnicalsKpiStrip } from "../panels/TechnicalsKpiStrip";
import { TechnicalsAnchorChart } from "../panels/TechnicalsAnchorChart";
import { LiveBadge } from "../panels/LiveBadge";
import {
  TechnicalsKinematicsChart,
  TechnicalsMacdChart,
  TechnicalsRsChart,
  TechnicalsRsiChart,
  TechnicalsVolChart,
  TechnicalsZChart,
} from "../panels/TechnicalsOscillators";
import { ForwardReturnTable } from "../panels/ForwardReturnTable";
import { TechnicalsDetailPanels } from "../panels/TechnicalsDetailPanels";

type State = {
  ticker: string;
  data: TechnicalsResponse | null;
  error: string | null;
};

// Client-side freshness gate — mirrors the server's default
// TECHNICAL_LIVE_QUOTE_MAX_AGE_SECONDS (900). Beyond this the live head is
// dropped and the EOD daily payload stands.
const LIVE_MAX_AGE_SEC = 900;

function isFresh(live: TechnicalsLiveResponse | null): boolean {
  if (!live?.available || !live.captured_at) return false;
  const age = (Date.now() - new Date(live.captured_at).getTime()) / 1000;
  return Number.isFinite(age) && age <= LIVE_MAX_AGE_SEC;
}

// Splice the live reading onto the daily payload: append one series row (which
// moves the last point of EVERY oscillator chart — z, RSI, dual MACD, RV,
// kinematics — at once) and override the latest detail readouts that drive the
// per-panel headlines. Sigmoid / forward-returns are intentionally untouched
// (static intraday). Returns the original data unchanged when live is stale.
function mergeLiveHead(
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
  const asOf = live.captured_at!.slice(0, 10);
  const liveRow = {
    as_of: asOf,
    close: live.spot ?? null,
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
  // Replace the last row if the live capture is same-day, else append.
  const last = series[series.length - 1];
  if (last && asOf && last.as_of === asOf) {
    series[series.length - 1] = { ...last, ...liveRow };
  } else {
    series.push(liveRow as (typeof series)[number]);
  }
  const detail = { ...(data.detail ?? {}) };
  detail.dual_macd = live.dual_macd ?? detail.dual_macd;
  detail.rsi = { ...(detail.rsi ?? {}), rsi14: live.rsi14 };
  detail.distribution = { ...(detail.distribution ?? {}), rv20: live.rv20 };
  return { ...data, series, detail };
}

export function TechnicalsTab({ ticker }: { ticker: string }) {
  const [state, setState] = useState<State>({
    ticker,
    data: null,
    error: null,
  });
  const [live, setLive] = useState<TechnicalsLiveResponse | null>(null);

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

  const ready = state.ticker === ticker;
  const error = ready ? state.error : null;
  const baseData = ready ? state.data : null;
  const liveForTicker = live?.ticker === ticker ? live : null;
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
      <div style={{ color: "var(--text-muted)", padding: 16 }}>
        No technicals history for {ticker} yet — populated by the nightly
        refresh (or run scripts/backfill/technicals_refresh_backfill.py).
      </div>
    );
  }
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div style={{ display: "flex", justifyContent: "flex-end" }}>
        <LiveBadge
          captured_at={liveForTicker?.captured_at ?? null}
          source={liveForTicker?.spot_source ?? null}
          maxAgeSec={LIVE_MAX_AGE_SEC}
        />
      </div>
      <TechnicalsKpiStrip data={data} />
      {/* Aligned stack: price on top, oscillators share its date axis below. */}
      <TechnicalsAnchorChart data={data} />
      <TechnicalsZChart data={data} />
      <TechnicalsRsiChart data={data} />
      <TechnicalsMacdChart data={data} />
      <TechnicalsVolChart data={data} />
      <TechnicalsKinematicsChart data={data} />
      <TechnicalsRsChart data={data} />
      <ForwardReturnTable data={data} />
      <TechnicalsDetailPanels data={data} />
    </div>
  );
}
