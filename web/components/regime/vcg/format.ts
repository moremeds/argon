/* ─── Helpers (1:1 port from xenon VcgPanel.tsx) ───────────────── */

// Persisted attribution percentages should already sum to 100, but the UI
// renders from JSONB and a corrupted/backfilled payload could surface NaN,
// Infinity, or values > 100 — clamp defensively so the bar can't overflow.
export function clampPct(v: number | null | undefined): number {
  if (v == null || !Number.isFinite(v)) return 0;
  return Math.min(100, Math.max(0, v));
}

export function interpretationColor(interpretation: string): string {
  switch (interpretation) {
    case "RISK_OFF":
      return "var(--fault, var(--negative))";
    case "EDR":
    case "WATCH":
      return "var(--warning)";
    case "BOUNCE":
    case "NORMAL":
      return "var(--signal-core, var(--positive))";
    case "PANIC":
      return "var(--extreme, var(--negative))";
    case "SUPPRESSED":
      return "var(--text-muted)";
    default:
      return "var(--text-muted)";
  }
}

export function interpretationLabel(interpretation: string): string {
  switch (interpretation) {
    case "RISK_OFF":
      return "RISK-OFF";
    case "EDR":
      return "EARLY DIVERGENCE";
    case "WATCH":
      return "WATCH";
    case "BOUNCE":
      return "BOUNCE";
    case "NORMAL":
      return "NORMAL";
    case "PANIC":
      return "PANIC";
    case "SUPPRESSED":
      return "SUPPRESSED";
    default:
      return "INSUFFICIENT DATA";
  }
}

export function regimeBadgeColor(regime: string): string {
  switch (regime) {
    case "PANIC":
      return "var(--extreme, var(--negative))";
    case "TRANSITION":
      return "var(--warning)";
    default:
      return "var(--signal-core, var(--positive))";
  }
}

export function tierColor(tier: number | null | undefined): string {
  switch (tier) {
    case 1:
    case 2:
      return "var(--fault, var(--negative))";
    case 3:
      return "var(--warning)";
    default:
      return "var(--text-muted)";
  }
}

export function tierLabel(tier: number | null | undefined): string {
  switch (tier) {
    case 1:
      return "TIER 1 — CRITICAL";
    case 2:
      return "TIER 2 — HIGH";
    case 3:
      return "TIER 3 — ELEVATED";
    default:
      return "NO ACTIVE TIER";
  }
}

export function vvixSeverityColor(sev: string): string {
  switch (sev) {
    case "extreme":
      return "var(--fault, var(--negative))";
    case "elevated":
      return "var(--warning)";
    default:
      return "var(--signal-core, var(--positive))";
  }
}

export function vvixSeverityDesc(sev: string): string {
  switch (sev) {
    case "extreme":
      return "VVIX far above 120 — maximum vol-of-vol stress";
    case "elevated":
      return "VVIX above 110 — second-order stress signal";
    default:
      return "VVIX below 110 — vol regime stable";
  }
}

/* v2 absolute-vol-stress override gate threshold (matches VIX_PCT_PANIC /
 * VVIX_PCT_PANIC constants in src/uw_scan/cards/vcg_scoring.py). When BOTH
 * 252-day percentile ranks clear 0.95, the v2 cascade fires RISK_OFF even
 * if sign_ok is false — bypassing the SUPPRESSED clause that masked PANIC
 * days in v1. */
const VOL_STRESS_THRESHOLD = 0.95;

export function formatPctRank(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

export function pctRankColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  if (v >= VOL_STRESS_THRESHOLD) return "var(--fault, var(--negative))";
  if (v >= 0.85) return "var(--warning)";
  return "var(--text-primary)";
}
