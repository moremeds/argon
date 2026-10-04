import type { GrgEventStats } from "@/lib/regime/useGrgLive";

export const METHODOLOGY =
  "GRG = z-score of (SPY gamma-z − TLT gamma-z) over a 63-session window. " +
  "Positive dealer gamma cushions moves; negative gamma whips them. A SPY/TLT " +
  "divergence flags a cross-asset risk rotation. DESCRIPTIVE indicator — the " +
  "gamma→vol mechanic is peer-reviewed, but the cross-asset gap signal is an " +
  "unvalidated hypothesis. A YTD forward-return backtest shows the gate-" +
  "confirmed top/bottom days LEAD the turn (early-warning), not mark it. See " +
  "docs/research/grg-gamma-rotation-gap.";

// Caveat for the chart's TOP-WATCH / BOTTOM-WATCH dots, anchored by the YTD
// backtest. Explains they lead the turn and clear a weaker historical bar.
export const BACKTEST_HELP =
  "Dots mark gate-confirmed TOP-WATCH / BOTTOM-WATCH days — early-warning " +
  "signals of building dealer-gamma conditions, NOT the exact turn. On the " +
  "YTD sample they LED the actual extreme: bottom-watches preceded a further " +
  "decline, the top-watch a further rise. Historical markers also omit the " +
  "gamma-flip gate (UW history has no per-day flip), so they clear a weaker " +
  "bar than the live headline signal. Descriptive, small-sample — not a " +
  "predictive turn-caller.";

// One-line summary of the YTD forward-return backtest, built from the
// persisted aggregate. Empty string when there is nothing to report.
export function backtestSummary(stats: GrgEventStats | undefined): string {
  if (!stats) return "";
  const side = (label: string, s: GrgEventStats["bottoms"] | undefined) => {
    if (!s || !s.n) return null;
    if (s.median_lead_sessions == null || s.median_extreme_gap_pct == null) {
      return `${s.n} ${label}`;
    }
    const gap = s.median_extreme_gap_pct;
    return `${s.n} ${label} led by ~${Math.round(
      s.median_lead_sessions,
    )} sessions (SPY ${gap >= 0 ? "+" : ""}${gap.toFixed(1)}% further)`;
  };
  const parts = [
    side("BOTTOM-WATCH", stats.bottoms),
    side("TOP-WATCH", stats.tops),
  ].filter(Boolean);
  if (!parts.length) return "";
  return `Backtest (YTD, ${stats.fwd_window}-session window): ${parts.join(
    " · ",
  )}. Early-warning, not the turn.`;
}

// Explainer for the per-asset badge — scoped to the asset's actual state so
// a WHIP card shows only the whip meaning, a CUSHION card only the cushion.
export function assetStateHelp(state: string | null | undefined): string {
  switch (state) {
    case "CUSHION":
      return "CUSHION: dealer gamma is positive — hedging mechanically dampens this asset's moves (stabilizing).";
    case "WHIP":
      return "WHIP: dealer gamma is negative — hedging mechanically amplifies this asset's moves (destabilizing).";
    default:
      return "NEUTRAL: dealer gamma is near zero — little mechanical push on this asset's moves.";
  }
}

export function fmtGex(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "---";
  // radon shows a signed magnitude ("-702.1K", "+7.7M").
  const sign = v > 0 ? "+" : v < 0 ? "-" : "";
  const abs = Math.abs(v);
  if (abs >= 1e9) return `${sign}${(abs / 1e9).toFixed(1)}B`;
  if (abs >= 1e6) return `${sign}${(abs / 1e6).toFixed(1)}M`;
  if (abs >= 1e3) return `${sign}${(abs / 1e3).toFixed(1)}K`;
  return `${sign}${abs.toFixed(0)}`;
}

export function gexColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  return v >= 0 ? "var(--positive)" : "var(--negative)";
}

export function gateColor(status: string): string {
  switch (status) {
    case "PASS":
      return "var(--positive)";
    case "FAIL":
      return "var(--negative)";
    default:
      return "var(--warning)";
  }
}

// Regime sentiment color, shared by the hero residual/label and the event rows.
export function pairStateColor(state: string | null | undefined): string {
  if (state === "RISK_OFF_DIVERGENCE" || state === "DUAL_WHIP")
    return "var(--negative)";
  if (state === "RISK_ON_DIVERGENCE" || state === "DUAL_CUSHION")
    return "var(--positive)";
  return "var(--text-muted)";
}

export function shortState(state: string | null | undefined): string {
  switch (state) {
    case "RISK_ON_DIVERGENCE":
      return "RISK-ON";
    case "RISK_OFF_DIVERGENCE":
      return "RISK-OFF";
    case "DUAL_WHIP":
      return "DUAL WHIP";
    case "DUAL_CUSHION":
      return "DUAL CUSHION";
    default:
      return "NEUTRAL";
  }
}

// GRG σ colored by sign (no dead band) — a -0.79σ reads red, +2.1σ reads green.
export function sigmaColor(z: number | null | undefined): string {
  if (z == null || !Number.isFinite(z)) return "var(--text-muted)";
  if (z < 0) return "var(--negative)";
  if (z > 0) return "var(--positive)";
  return "var(--text-primary)";
}
