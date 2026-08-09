"use client";

import { useEffect, useState, type ReactNode } from "react";

import { api, type MagnetsResponse, type TechnicalsResponse } from "@/lib/api";
import { AnalyticalSeriesPanel } from "@/components/stock/panels/AnalyticalSeriesPanel";
import { sma, velocity } from "@/lib/magnetTiles";
import MagnetChart from "./MagnetChart";
import MagnetRead from "./MagnetRead";
import MagnetTable from "./MagnetTable";
import { IvChart, MomentumChart, RsiChart, VolumeChart } from "./MagnetTiles";

// Measured coverage per horizon, from the Phase 1 calibration. Kept here as the
// single legend source; the numbers themselves come off the API per band.
const BAND_NOTE: Record<number, string> = {
  5: "",
  10: "",
  21: " · 21d errors run narrow; treat this band as a floor",
};

/** Sessions the RSI / momentum / IV tile charts cover. */
const TILE_BARS = 90;
/** Volume bars get a shorter window — 90 bars at tile width are 1px slivers. */
const VOL_BARS = 34;
/** Sessions per kinematics leg (velocity now vs velocity one leg ago). */
const KIN = 5;

export default function MagnetSubTab({
  ticker,
  technicals,
}: {
  ticker: string;
  technicals: TechnicalsResponse | null;
}) {
  // The fetched payload carries the ticker it belongs to, so a mismatch IS the
  // loading state. The obvious alternative — setData(null) at the top of the
  // effect — is a synchronous setState inside an effect: it costs a cascading
  // render and `react-hooks/set-state-in-effect` rejects it. Tagging makes it
  // impossible to render one ticker's levels under another's header at all,
  // rather than merely unlikely.
  const [fetched, setFetched] = useState<{
    ticker: string;
    body: MagnetsResponse | null;
    error: string | null;
  } | null>(null);

  useEffect(() => {
    let live = true;
    api
      .magnets(ticker)
      .then((d) => live && setFetched({ ticker, body: d, error: null }))
      .catch(
        (e) => live && setFetched({ ticker, body: null, error: String(e) }),
      );
    return () => {
      live = false;
    };
  }, [ticker]);

  const current = fetched?.ticker === ticker ? fetched : null;
  const data = current?.body ?? null;
  const error = current?.error ?? null;

  if (error)
    return (
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        {error}
      </div>
    );
  if (!data)
    return (
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        Loading…
      </div>
    );

  // rsi14 lives on TechnicalsSeriesRow, NOT on TechnicalsResponse — the response
  // carries `series: TechnicalsSeriesRow[]`. Read the last row.
  const series = technicals?.series ?? [];
  const row = series.at(-1) ?? null;
  const tail = series.slice(-TILE_BARS);
  const rsi = row?.rsi14 ?? null;
  const iv = data.atm_iv_30d;
  const dIv = data.atm_iv_30d_chg_5d;
  const state = data.levels?.leg_state ?? "no swing";

  // Volume comes off the CANDLES, not technicals.series — the two sources sit on
  // different as_of dates (see the panel subtitle), and the bars must line up
  // with the chart directly above them.
  const volBars = data.candles.slice(-VOL_BARS).map((c) => ({
    volume: c.volume,
    up: c.close >= c.open,
  }));
  const volMa = sma(
    data.candles.map((c) => c.volume),
    20,
  ).slice(-VOL_BARS);
  const lastVol = data.candles.at(-1)?.volume ?? null;
  const lastVolMa = volMa.at(-1) ?? null;

  // Kinematics, spec §1.1 layer 6: 1st and 2nd derivative of price. Descriptive
  // only — no threshold is applied and no ACCEL/DECEL verdict is printed,
  // because picking those cut-offs would be inventing a signal the reference
  // never validated either.
  const closes = data.candles.map((c) => c.close);
  const n = closes.length;
  const v = velocity(closes, n - 1 - KIN, n - 1);
  const vPrev = velocity(closes, n - 1 - 2 * KIN, n - 1 - KIN);
  const accel = v != null && vPrev != null ? (v - vPrev) / KIN : null;

  const ivSeries = data.atm_iv_30d_series.map((p) => p.iv * 100);

  const pct = (x: number) => `${x >= 0 ? "+" : ""}${(x * 100).toFixed(1)}%`;
  const sgn = (x: number, d = 2) => `${x >= 0 ? "+" : ""}${x.toFixed(d)}`;

  const tiles: {
    label: string;
    headline: string;
    delta: string | null;
    caption?: string | null;
    chart: ReactNode;
  }[] = [
    {
      label: "VOLUME",
      headline: lastVol != null ? `${(lastVol / 1e6).toFixed(1)}M` : "na",
      delta:
        lastVol != null && lastVolMa
          ? `${(lastVol / lastVolMa).toFixed(2)}× avg`
          : null,
      chart: <VolumeChart bars={volBars} ma={volMa} />,
    },
    {
      label: "RSI 14",
      headline: rsi != null ? rsi.toFixed(1) : "na",
      delta: row?.rsi_slope5 != null ? `${sgn(row.rsi_slope5, 1)} 5d` : null,
      chart: <RsiChart values={tail.map((r) => r.rsi14)} />,
    },
    {
      label: "MOMENTUM",
      headline:
        row?.macd_hist_atr != null ? row.macd_hist_atr.toFixed(2) : "na",
      delta:
        row?.macd_slope3 != null
          ? `${row.macd_slope3 >= 0 ? "▲" : "▼"} 3d`
          : null,
      caption:
        v != null
          ? `v ${sgn(v)}%/d${accel != null ? ` · a ${sgn(accel)}%/d²` : ""}`
          : null,
      chart: (
        <MomentumChart
          fast={tail.map((r) => r.macd_hist_atr)}
          slow={tail.map((r) => r.slow_macd_hist_atr)}
        />
      ),
    },
    {
      label: "ATM IV",
      headline: iv != null ? pct(iv).replace("+", "") : "na",
      delta: dIv != null ? `${sgn(dIv * 100, 1)}pt 5d` : null,
      // Sessions with no captured surface are absent from the series, so a
      // short line here means a short capture history, not flat vol.
      caption: ivSeries.length > 1 ? null : "surface capture too short to plot",
      chart: ivSeries.length > 1 ? <IvChart values={ivSeries} /> : null,
    },
  ];

  return (
    <div
      data-testid="magnet-subtab"
      style={{ display: "flex", flexDirection: "column", gap: 12 }}
    >
      <AnalyticalSeriesPanel
        title="magnet levels — 0.618 measured move"
        // The source table and its date are named here because this sub-tab
        // reads `daily_ohlc` while the rest of the Technicals tab reads
        // `technical_daily`. The two can and do diverge (13 sessions apart on
        // the local dev DB), and an unlabelled chart silently disagreeing with
        // the KPI strip above it is worse than a stale one you can see.
        subtitle={`daily_ohlc · ${data.as_of} · candles · sma20 · zigzag pivots · volume magnets · options-implied cone`}
        headline={
          <span style={{ color: "var(--positive)" }}>
            {data.ticker} · {state.toUpperCase()}
          </span>
        }
      >
        <MagnetChart data={data} />

        {/* Spec §5.1 item 3: four tiles, label left / headline + delta right,
            each over its own trend line. "na" is rendered literally when a
            source is missing — never a zero or a dash that could read as a
            real reading. */}
        <div
          data-testid="magnet-tiles"
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(4, 1fr)",
            gap: 8,
            marginTop: 12,
          }}
        >
          {tiles.map((t) => (
            <div
              key={t.label}
              style={{
                padding: "6px 10px 8px",
                border: "1px solid var(--border-dim)",
                borderRadius: 4,
                fontFamily: "var(--font-mono)",
                fontSize: 11,
              }}
            >
              <div
                style={{
                  display: "flex",
                  justifyContent: "space-between",
                  alignItems: "baseline",
                }}
              >
                <span style={{ opacity: 0.55, letterSpacing: 0.5 }}>
                  {t.label}
                </span>
                <span>
                  <strong style={{ fontSize: 13 }}>{t.headline}</strong>
                  {t.delta ? (
                    <span style={{ opacity: 0.5, marginLeft: 6 }}>
                      {t.delta}
                    </span>
                  ) : null}
                </span>
              </div>
              {t.caption ? (
                <div style={{ fontSize: 9, opacity: 0.45, marginTop: 2 }}>
                  {t.caption}
                </div>
              ) : null}
              {t.chart}
            </div>
          ))}
        </div>
      </AnalyticalSeriesPanel>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <AnalyticalSeriesPanel
          title="levels"
          subtitle={
            data.levels
              ? `${state} leg · ${data.levels.pivot_a.kind} → ${data.levels.pivot_b.kind}`
              : "no confirmed swing"
          }
        >
          <MagnetTable levels={data.levels} />
        </AnalyticalSeriesPanel>
        <AnalyticalSeriesPanel
          title="the read"
          subtitle={
            rsi != null
              ? `rsi ${rsi.toFixed(1)} · deterministic template`
              : "deterministic template"
          }
        >
          <MagnetRead read={data.read} />
        </AnalyticalSeriesPanel>
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          opacity: 0.5,
          fontStyle: "italic",
        }}
      >
        {data.bands
          .filter((b) => b.band_sigma === 1.96)
          .map(
            (b) =>
              `${b.horizon}d 1.96σ band held ${Math.round(b.measured_confidence * 100)}% of moves ` +
              `(${(b.measured_ci_lo * 100).toFixed(1)}–${(b.measured_ci_hi * 100).toFixed(1)}%, ` +
              `${b.measured_n_dates} sessions, Dec 2025–Jul 2026)${BAND_NOTE[b.horizon] ?? ""}`,
          )
          .join("   ·   ")}
      </div>
    </div>
  );
}
