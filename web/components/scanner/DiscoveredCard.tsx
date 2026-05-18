"use client";
import Link from "next/link";
import { useState } from "react";
import { useRouter } from "next/navigation";

import { api } from "@/lib/api";
import type { components } from "@/lib/types";

import { SignalRow } from "./SignalRow";

type Discovered = components["schemas"]["DiscoveryCandidate"];
type Bias = Discovered["bias"];
type BiasStrength = NonNullable<Discovered["bias_strength"]>;

const BIAS_COLOR: Record<Bias, string> = {
  bullish: "var(--positive)",
  bearish: "var(--negative)",
  mixed: "var(--warning)",
  neutral: "var(--text-muted)",
};

const BIAS_ARROW: Record<Bias, string> = {
  bullish: "▲",
  bearish: "▼",
  mixed: "◆",
  neutral: "—",
};

type AddState = "idle" | "adding" | "added" | "failed";

function BiasBadge({
  bias,
  strength,
}: {
  bias: Bias;
  strength: BiasStrength | null | undefined;
}) {
  if (bias === "neutral") return null;
  const color = BIAS_COLOR[bias];
  return (
    <div
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        color,
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
      }}
    >
      <span style={{ fontSize: 12 }}>{BIAS_ARROW[bias]}</span>
      {strength ? (
        <span style={{ color: "var(--text-muted)" }}>{strength}</span>
      ) : null}
    </div>
  );
}

function freshnessLabel(iso: string | null | undefined, nowMs: number): string {
  if (!iso) return "unknown";
  const minutes = Math.max(
    0,
    Math.round((nowMs - new Date(iso).getTime()) / 60_000),
  );
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

export function DiscoveredCard({
  candidate,
  nowMs,
}: {
  candidate: Discovered;
  // Optional only so jsdom unit tests can omit it. The /scanner RSC always
  // passes this so SSR + client hydration agree on the relative-time label.
  nowMs?: number;
}) {
  const anchor = nowMs ?? Date.now();
  const router = useRouter();
  const [add, setAdd] = useState<AddState>("idle");
  const tickerColor = BIAS_COLOR[candidate.bias];

  const onAdd = async () => {
    setAdd("adding");
    try {
      await api.addTicker({
        ticker: candidate.ticker,
        sector: candidate.sector ?? "Unknown",
        notes: "added from scanner discovery",
      });
      // Kick off a deep scan immediately so the ticker shows up in the curated
      // sections on next refresh rather than waiting for the next full_scan cron.
      await api.rescan(candidate.ticker);
      setAdd("added");
      router.refresh();
    } catch (e) {
      console.error(e);
      setAdd("failed");
    }
  };

  return (
    <div
      style={{
        padding: 12,
        background: "var(--bg-panel)",
        border: "1px solid var(--accent-vol)",
        borderRadius: 4,
        color: "var(--text-primary)",
        fontFamily: "var(--font-mono)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {/* Header: ticker + bias arrow */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 6 }}>
          <span
            style={{
              width: 6,
              height: 6,
              borderRadius: "50%",
              background: "var(--accent-vol)",
              display: "inline-block",
            }}
            title="Discovered outside your watchlist"
          />
          <span
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: tickerColor,
            }}
          >
            {candidate.ticker}
          </span>
          {candidate.sector ? (
            <span
              style={{
                fontSize: 10,
                color: "var(--text-muted)",
                fontWeight: 500,
              }}
            >
              {candidate.sector}
            </span>
          ) : null}
        </div>
        <BiasBadge bias={candidate.bias} strength={candidate.bias_strength} />
      </div>

      {/* Signal row — only DCF for discovered tickers */}
      <SignalRow hit={candidate.hit} />

      {/* Footer: DISCOVERED badge + score */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          borderTop: "1px solid var(--border-dim)",
          paddingTop: 8,
          marginTop: "auto",
        }}
      >
        <span
          title="Surfaced from the market-wide flow-alerts feed. Add to watchlist for the full Dark Pool / EIC / GEX scan."
          style={{
            display: "inline-flex",
            alignItems: "center",
            gap: 4,
            padding: "2px 6px",
            borderRadius: 3,
            backgroundColor: "var(--accent-vol)",
            color: "var(--bg-panel)",
            fontFamily: "var(--font-mono)",
            fontSize: 9,
            letterSpacing: 1.2,
            fontWeight: 700,
            cursor: "help",
          }}
        >
          DISCOVERED
        </span>
        <span
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: tickerColor,
            letterSpacing: 0.5,
          }}
        >
          {Number(candidate.hit.score).toFixed(2)}
        </span>
      </div>

      {/* Bottom: last-seen + actions */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 10,
          color: "var(--text-muted)",
        }}
      >
        <span>
          {candidate.alert_count} alerts · last{" "}
          {freshnessLabel(candidate.latest_alert_at, anchor)} ago
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <button
            type="button"
            aria-label={`Add ${candidate.ticker} to watchlist`}
            onClick={onAdd}
            disabled={add === "adding" || add === "added"}
            style={{
              fontSize: 10,
              fontFamily: "var(--font-mono)",
              padding: "2px 6px",
              background: "transparent",
              color: "var(--accent-warm)",
              border: "1px solid var(--accent-warm)",
              borderRadius: 2,
              cursor: add === "adding" ? "wait" : "pointer",
            }}
          >
            {add === "idle"
              ? "+ Watchlist"
              : add === "adding"
                ? "adding…"
                : add === "added"
                  ? "✓ added"
                  : "✗ failed"}
          </button>
          {add === "added" ? (
            <Link
              href={`/stock/${candidate.ticker}/trade-plan`}
              style={{
                color: "var(--accent-warm)",
                textDecoration: "none",
                fontSize: 11,
              }}
            >
              Evaluate →
            </Link>
          ) : null}
        </div>
      </div>
    </div>
  );
}
