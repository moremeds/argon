"use client";
import Link from "next/link";

import { RescanButton } from "@/components/shared/RescanButton";
import { bucketFreshness } from "@/lib/freshness";
import type { components } from "@/lib/types";

import { ContextFlagBadge } from "./ContextFlagBadge";
import { SignalRow } from "./SignalRow";

type Candidate = components["schemas"]["ScannerCandidate"];
type Bias = Candidate["bias"];
type BiasStrength = NonNullable<Candidate["bias_strength"]>;
type Setup = Candidate["setup"];

const SCANNER_FRESHNESS_THRESHOLDS = {
  freshMinutes: 8 * 60,
  staleMinutes: 72 * 60,
};

const DOT_COLOR: Record<"fresh" | "stale" | "dead", string> = {
  fresh: "var(--positive)",
  stale: "var(--warning)",
  dead: "var(--negative)",
};

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

const SETUP_COLOR: Record<Setup, string> = {
  ready: "var(--positive)",
  caution: "var(--warning)",
  blocked: "var(--negative)",
};

const SETUP_WORD: Record<Setup, string> = {
  ready: "READY",
  caution: "CAUTION",
  blocked: "BLOCKED",
};

function setupTooltip(setup: Setup, reason: string | null | undefined): string {
  switch (setup) {
    case "ready":
      return "All risk gates pass — no earnings in window, liquidity OK, regime allows direction. This is a filter result, not a buy signal.";
    case "caution":
      return reason === "earnings"
        ? "Earnings event sits inside the trade window — IV crush risk. Size accordingly."
        : reason === "liquidity"
          ? "Option chain volume/OI is thin — entry and exit slippage will be high."
          : "A non-regime gate is flagging — proceed carefully.";
    case "blocked":
      return "Market regime vetoes this direction. Hard skip — do not trade against the tape.";
  }
}

function freshnessLabel(scannedAt: string, nowMs: number): string {
  const minutes = Math.max(
    0,
    Math.round((nowMs - new Date(scannedAt).getTime()) / 60_000),
  );
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m`;
  const hours = Math.round(minutes / 60);
  return `${hours}h`;
}

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

function SetupPill({
  setup,
  reason,
}: {
  setup: Setup;
  reason: string | null | undefined;
}) {
  const color = SETUP_COLOR[setup];
  const detail = setup === "ready" ? null : reason;
  return (
    <span
      title={setupTooltip(setup, reason)}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "2px 6px",
        borderRadius: 3,
        backgroundColor: color,
        color: "var(--bg-panel)",
        fontFamily: "var(--font-mono)",
        fontSize: 9,
        letterSpacing: 1.2,
        fontWeight: 700,
        cursor: "help",
      }}
    >
      <span>{SETUP_WORD[setup]}</span>
      {detail ? <span style={{ opacity: 0.85 }}>· {detail}</span> : null}
    </span>
  );
}

export function CandidateCard({
  candidate,
  nowMs,
}: {
  candidate: Candidate;
  // Optional only so jsdom unit tests can omit it. The /scanner RSC always
  // passes this so SSR + client hydration agree on the relative-time label.
  nowMs?: number;
}) {
  const anchor = nowMs ?? Date.parse(candidate.scanned_at);
  const fresh = bucketFreshness(
    candidate.scanned_at,
    new Date(anchor),
    SCANNER_FRESHNESS_THRESHOLDS,
  );
  const tickerColor = BIAS_COLOR[candidate.bias];
  const scoreColor = SETUP_COLOR[candidate.setup];

  return (
    <div
      style={{
        padding: 12,
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        color: "var(--text-primary)",
        fontFamily: "var(--font-mono)",
        display: "flex",
        flexDirection: "column",
        gap: 8,
      }}
    >
      {/* Header: dot + ticker + spot (left) · bias arrow + strength (right) */}
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
              background: DOT_COLOR[fresh],
              display: "inline-block",
            }}
          />
          {candidate.is_type_f ? (
            <span
              title="Multi-signal: 2+ independent signals lined up"
              style={{ color: "var(--accent-warm)", fontSize: 12 }}
            >
              *
            </span>
          ) : null}
          <span
            style={{
              fontSize: 16,
              fontWeight: 700,
              color: tickerColor,
            }}
          >
            {candidate.ticker}
          </span>
          <span
            style={{
              fontSize: 12,
              color: "var(--text-secondary)",
              fontWeight: 500,
            }}
          >
            {candidate.spot ? `$${candidate.spot}` : "—"}
          </span>
        </div>
        <BiasBadge bias={candidate.bias} strength={candidate.bias_strength} />
      </div>

      {/* Signals — one compact row per hit */}
      <div style={{ display: "flex", flexDirection: "column", gap: 4 }}>
        {candidate.hits.map((h) => (
          <SignalRow key={h.signal_type} hit={h} />
        ))}
      </div>

      {/* Context flags — render only if present */}
      {candidate.context_flags.length > 0 ? (
        <div style={{ display: "flex", flexWrap: "wrap", gap: 4 }}>
          {candidate.context_flags.map((f) => (
            <ContextFlagBadge key={f.layer} flag={f} />
          ))}
        </div>
      ) : null}

      {/* Setup + score — pinned to bottom so the divider aligns across the row */}
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
        <SetupPill setup={candidate.setup} reason={candidate.setup_reason} />
        <span
          style={{
            fontSize: 22,
            fontWeight: 700,
            color: scoreColor,
            letterSpacing: 0.5,
          }}
        >
          {Number(candidate.final_score).toFixed(2)}
        </span>
      </div>

      {/* Footer: freshness + actions */}
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "center",
          fontSize: 10,
          color: "var(--text-muted)",
        }}
      >
        <span>scanned {freshnessLabel(candidate.scanned_at, anchor)} ago</span>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <RescanButton ticker={candidate.ticker} initialJob={null} />
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
        </div>
      </div>
    </div>
  );
}
