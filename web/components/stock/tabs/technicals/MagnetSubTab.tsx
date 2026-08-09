"use client";

import { useEffect, useState } from "react";

import { api, type MagnetsResponse, type TechnicalsResponse } from "@/lib/api";
import MagnetRead from "./MagnetRead";
import MagnetTable from "./MagnetTable";

// Measured coverage per horizon, from the Phase 1 calibration. Kept here as the
// single legend source; the numbers themselves come off the API per band.
const BAND_NOTE: Record<number, string> = {
  5: "",
  10: "",
  21: " · 21d errors run narrow; treat this band as a floor",
};

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
  const row = technicals?.series?.at(-1) ?? null;
  const rsi = row?.rsi14 ?? null;
  const iv = data.atm_iv_30d;
  const dIv = data.atm_iv_30d_chg_5d;
  const state = data.levels?.leg_state ?? "no swing";

  const pct = (v: number) => `${v >= 0 ? "+" : ""}${(v * 100).toFixed(1)}%`;
  const tiles: { label: string; headline: string; delta: string | null }[] = [
    {
      label: "VOLUME",
      headline:
        row?.volume != null ? `${(row.volume / 1e6).toFixed(1)}M` : "na",
      delta: null,
    },
    {
      label: "RSI 14",
      headline: rsi != null ? rsi.toFixed(1) : "na",
      delta:
        row?.rsi_slope5 != null
          ? `${row.rsi_slope5 >= 0 ? "+" : ""}${row.rsi_slope5.toFixed(1)} 5d`
          : null,
    },
    {
      label: "MOMENTUM",
      headline:
        row?.macd_hist_atr != null ? row.macd_hist_atr.toFixed(2) : "na",
      delta:
        row?.macd_slope3 != null
          ? `${row.macd_slope3 >= 0 ? "▲" : "▼"} 3d`
          : null,
    },
    {
      label: "ATM IV",
      headline: iv != null ? pct(iv).replace("+", "") : "na",
      delta:
        dIv != null
          ? `${dIv >= 0 ? "+" : ""}${(dIv * 100).toFixed(1)}pt 5d`
          : null,
    },
  ];

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <div>
        <div style={{ fontSize: 20, fontWeight: 800, color: "#4ade80" }}>
          {data.ticker} · {state.toUpperCase()}
        </div>
        <div
          style={{ fontFamily: "var(--font-mono)", fontSize: 11, opacity: 0.6 }}
        >
          {[
            state,
            rsi != null ? `RSI ${rsi.toFixed(1)}` : null,
            data.levels
              ? `${data.levels.pivot_b.kind} @ ${data.levels.pivot_b.price.toFixed(2)}`
              : null,
            iv != null
              ? `ATM IV ${(iv * 100).toFixed(1)}%${dIv != null ? ` (${dIv >= 0 ? "+" : ""}${(dIv * 100).toFixed(1)}pt 5d)` : ""}`
              : null,
          ]
            .filter(Boolean)
            .join(" | ")}
        </div>
      </div>

      {/* Task 6 replaces this line with <MagnetChart data={data} />. Left as a
          placeholder so THIS task typechecks on its own — importing a component
          the next task creates makes Step 7's `npm run typecheck` fail. */}
      <div
        style={{
          height: 420,
          opacity: 0.4,
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
      >
        chart pending (Task 6)
      </div>

      {/* Spec §5.1 item 3: four tiles, label left / headline + delta right.
          "na" is rendered literally when a source is missing — never a zero or a
          dash that could read as a real reading. */}
      <div
        data-testid="magnet-tiles"
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, 1fr)",
          gap: 8,
        }}
      >
        {tiles.map((t) => (
          <div
            key={t.label}
            style={{
              display: "flex",
              justifyContent: "space-between",
              alignItems: "baseline",
              padding: "6px 10px",
              border: "1px solid rgba(255,255,255,0.08)",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            <span style={{ opacity: 0.55, letterSpacing: 0.5 }}>{t.label}</span>
            <span>
              <strong style={{ fontSize: 13 }}>{t.headline}</strong>
              {t.delta ? (
                <span style={{ opacity: 0.5, marginLeft: 6 }}>{t.delta}</span>
              ) : null}
            </span>
          </div>
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <MagnetTable levels={data.levels} />
        <MagnetRead read={data.read} />
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
