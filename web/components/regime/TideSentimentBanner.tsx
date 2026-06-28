"use client";

import type { MarketTideSentiment } from "@/lib/regime/useMarketTide";

function fmtHr(v: number | null): string {
  if (v == null) return "—";
  const m = v / 1_000_000;
  if (Math.abs(m) >= 1000) return `${(m / 1000).toFixed(1)}B/hr`;
  return `${m >= 0 ? "+" : ""}${m.toFixed(0)}M/hr`;
}

function fmtM(v: number | null): string {
  if (v == null) return "—";
  const m = v / 1_000_000;
  if (Math.abs(m) >= 1000)
    return `${m >= 0 ? "+" : ""}${(m / 1000).toFixed(1)}B`;
  return `${m >= 0 ? "+" : ""}${m.toFixed(0)}M`;
}

function stateColor(state: string): string {
  if (state === "BULLISH") return "var(--positive, #22c55e)";
  if (state === "BEARISH") return "var(--negative, #ef4444)";
  return "var(--text-muted)";
}

export function TideSentimentBanner({
  sentiment,
}: {
  sentiment: MarketTideSentiment | null;
}) {
  if (!sentiment) return null;
  const s = sentiment;
  const color = stateColor(s.state);
  const arrow = s.state === "BULLISH" ? "▲" : s.state === "BEARISH" ? "▼" : "•";
  const trend =
    s.trend_strength != null ? `${Math.round(s.trend_strength * 100)}%` : "—";

  return (
    <div
      data-testid="tide-sentiment-banner"
      style={{
        display: "flex",
        flexWrap: "wrap",
        alignItems: "center",
        gap: 14,
        padding: "8px 12px",
        borderRadius: 4,
        border: `1px solid ${color}`,
        background: "rgba(148,163,184,0.04)",
        fontFamily: "var(--font-mono)",
        fontSize: 12,
      }}
    >
      <span
        style={{
          color: "var(--text-muted)",
          letterSpacing: "0.08em",
          fontSize: 11,
        }}
      >
        TIDE SENTIMENT
      </span>
      <span
        title="Slope of the net call−put premium spread. Flow descriptor, not a price predictor."
        style={{
          color,
          fontWeight: 700,
          letterSpacing: "0.04em",
          cursor: "help",
        }}
      >
        {arrow} {s.state}
        {s.state !== "BALANCED" && s.state !== "WARMING_UP"
          ? ` · ${s.magnitude}`
          : ""}
      </span>
      {s.driver !== "—" && (
        <span style={{ color: "var(--text-secondary)" }}>{s.driver}</span>
      )}
      {s.momentum !== "—" && (
        <span style={{ color: "var(--text-muted)" }}>{s.momentum}</span>
      )}
      {s.volume_confirms != null && (
        <span
          style={{
            color: s.volume_confirms
              ? "var(--positive, #22c55e)"
              : "var(--warning, #F5A623)",
          }}
        >
          {s.volume_confirms ? "vol confirms" : "vol unconfirmed"}
        </span>
      )}
      <span style={{ marginLeft: "auto", color: "var(--text-muted)" }}>
        divergence {trend} · spread {fmtM(s.spread)} · slope{" "}
        {fmtHr(s.session_slope)}
      </span>
    </div>
  );
}
