import type { components } from "@/lib/types";

type Hit = components["schemas"]["ScannerSignalHit"];

const TIER_BG: Record<1 | 2, string> = {
  1: "var(--accent-warm)",
  2: "var(--accent-bg)",
};

const LABEL_BY_TYPE: Record<Hit["signal_type"], string> = {
  deep_conviction_flow: "DCF",
  dark_pool_accumulation: "DP",
  earnings_iv_crush: "EIC",
  gex_pinning: "GEX",
};

function formatShortUsd(n: number): string {
  if (n >= 1_000_000) return `${(n / 1_000_000).toFixed(1)}M`;
  if (n >= 1_000) return `${(n / 1_000).toFixed(0)}K`;
  return n.toFixed(0);
}

function toDisplay(value: unknown): string | null {
  if (value == null) return null;
  if (typeof value === "string" || typeof value === "number") {
    return String(value);
  }
  return null;
}

function toNumber(value: unknown): number | null {
  if (typeof value === "number") return value;
  if (typeof value === "string" && value.trim() !== "") {
    const parsed = Number(value);
    return Number.isFinite(parsed) ? parsed : null;
  }
  return null;
}

function describeEvidence(h: Hit): string {
  switch (h.signal_type) {
    case "deep_conviction_flow": {
      const premium = toNumber(h.evidence.total_premium);
      const dte = toDisplay(h.evidence.top_dte);
      return [
        premium != null ? `$${formatShortUsd(premium)}` : null,
        dte != null ? `${dte} DTE` : null,
      ]
        .filter(Boolean)
        .join(" · ");
    }
    case "dark_pool_accumulation": {
      const size = toDisplay(h.evidence.cluster_size) ?? "?";
      const price = toDisplay(h.evidence.anchor_price);
      return `cluster of ${size}${price ? ` @ $${price}` : ""}`;
    }
    case "earnings_iv_crush": {
      const iv = toDisplay(h.evidence.iv_rank);
      const dte = toDisplay(h.evidence.earnings_within_days);
      return [
        iv ? `iv_rank ${iv}` : null,
        dte != null ? `earn in ${dte}d` : null,
      ]
        .filter(Boolean)
        .join(" · ");
    }
    case "gex_pinning": {
      const pin = toDisplay(h.evidence.strike);
      const dist = toNumber(h.evidence.distance_pct);
      return `pin ${pin ?? "?"}${dist != null ? ` (${dist.toFixed(2)}%)` : ""}`;
    }
  }
}

export function SignalBadge({ hit }: { hit: Hit }) {
  const tier = hit.tier === 1 ? 1 : 2;
  return (
    <span
      style={{
        display: "inline-block",
        padding: "2px 8px",
        marginRight: 8,
        borderRadius: 3,
        backgroundColor: TIER_BG[tier],
        color: "var(--text-primary)",
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        letterSpacing: 0.5,
      }}
    >
      {LABEL_BY_TYPE[hit.signal_type]} · tier {hit.tier} ·{" "}
      {describeEvidence(hit)}
    </span>
  );
}
