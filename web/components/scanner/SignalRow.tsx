import type { components } from "@/lib/types";

type Hit = components["schemas"]["ScannerSignalHit"];

const TIER_COLOR: Record<1 | 2, string> = {
  1: "var(--accent-warm)",
  2: "var(--accent-bg)",
};

const LABEL_BY_TYPE: Record<Hit["signal_type"], string> = {
  deep_conviction_flow: "Conviction Flow",
  dark_pool_accumulation: "Dark Pool",
  earnings_iv_crush: "Earnings IV Crush",
  gex_pinning: "Gamma Pin",
};

function formatShortUsd(n: number): string {
  if (n >= 1_000_000_000) return `${(n / 1_000_000_000).toFixed(2)}B`;
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

function fmtExpiry(iso: string | null): string | null {
  if (!iso) return null;
  const m = iso.match(/^(\d{4})-(\d{2})-(\d{2})$/);
  if (!m) return null;
  const [, y, mo, d] = m;
  return `${mo}/${d}/${y.slice(2)}`;
}

function fmtContract(
  strike: string | null,
  optType: string | null,
): string | null {
  if (!strike) return null;
  const t = optType === "call" ? "C" : optType === "put" ? "P" : null;
  if (!t) return null;
  return `${t} ${strike}`;
}

function fmtAskPct(ratio: unknown): string | null {
  const n = toNumber(ratio);
  if (n == null) return null;
  return `${Math.round(n * 100)}% ask`;
}

function describeEvidence(h: Hit): string[] {
  switch (h.signal_type) {
    case "deep_conviction_flow": {
      const direction = toDisplay(h.evidence.direction);
      const premium = toNumber(h.evidence.total_premium);
      const alertCount = toDisplay(h.evidence.qualifying_alerts);
      const contract = fmtContract(
        toDisplay(h.evidence.top_strike),
        toDisplay(h.evidence.top_option_type),
      );
      const expiry = fmtExpiry(toDisplay(h.evidence.top_expiry));
      const dte = toDisplay(h.evidence.top_dte);
      const dateOrDte = expiry ?? (dte != null ? `${dte} DTE` : null);
      const askPct = fmtAskPct(h.evidence.top_ask_side_ratio);

      const line1 = [
        direction && direction !== "unknown" ? direction : null,
        premium != null ? `$${formatShortUsd(premium)}` : null,
        alertCount != null ? `${alertCount} alerts` : null,
      ]
        .filter(Boolean)
        .join(" · ");
      const line2 = [contract, dateOrDte, askPct].filter(Boolean).join(" · ");
      return [line1, line2].filter((s) => s.length > 0);
    }
    case "dark_pool_accumulation": {
      const size = toDisplay(h.evidence.cluster_size) ?? "?";
      const notional = toNumber(h.evidence.total_premium);
      const priceMin = toDisplay(h.evidence.cluster_price_min);
      const priceMax = toDisplay(h.evidence.cluster_price_max);
      const vwap =
        toDisplay(h.evidence.cluster_price_vwap) ??
        toDisplay(h.evidence.anchor_price);
      const vsSpot = toDisplay(h.evidence.vs_spot);
      const vsSpotPct = toNumber(h.evidence.vs_spot_pct);
      const vsSpotPiece =
        vsSpot && vsSpot !== "unknown"
          ? vsSpot === "at"
            ? "at spot"
            : vsSpotPct != null
              ? `${Math.abs(vsSpotPct).toFixed(2)}% ${vsSpot}`
              : vsSpot
          : null;
      // Prefer the explicit range when the detector emitted both min/max.
      // Fall back to the volume-weighted average or the legacy anchor for
      // backward-compat with hits persisted before the range was tracked.
      const priceRange =
        priceMin && priceMax && priceMin !== priceMax
          ? `$${priceMin}–$${priceMax}`
          : vwap
            ? `~$${vwap}`
            : null;
      return [
        [
          `${size} prints`,
          notional != null ? `$${formatShortUsd(notional)}` : null,
          priceRange,
          vsSpotPiece,
        ]
          .filter(Boolean)
          .join(" · "),
      ];
    }
    case "earnings_iv_crush": {
      const iv = toDisplay(h.evidence.iv_rank);
      const dte = toDisplay(h.evidence.earnings_within_days);
      return [
        [iv ? `IVR ${iv}` : null, dte != null ? `earn in ${dte}d` : null]
          .filter(Boolean)
          .join(" · "),
      ];
    }
    case "gex_pinning": {
      const pin = toDisplay(h.evidence.strike);
      const dist = toNumber(h.evidence.distance_pct);
      return [
        `pin ${pin ?? "?"}${dist != null ? ` (${dist.toFixed(2)}%)` : ""}`,
      ];
    }
  }
}

export function SignalRow({ hit }: { hit: Hit }) {
  const tier = hit.tier === 1 ? 1 : 2;
  const tierColor = TIER_COLOR[tier];
  const tierLabel = tier === 1 ? "primary" : "confirming";
  return (
    <div
      style={{
        display: "flex",
        flexDirection: "column",
        gap: 2,
        fontFamily: "var(--font-mono)",
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <span
          style={{
            fontSize: 10,
            letterSpacing: 1,
            color: tierColor,
            fontWeight: 700,
            textTransform: "uppercase",
          }}
        >
          {LABEL_BY_TYPE[hit.signal_type]}
        </span>
        <span
          style={{
            fontSize: 9,
            color: "var(--text-muted)",
            letterSpacing: 0.5,
          }}
          title={
            tier === 1
              ? "Primary signal — counts toward the score"
              : "Confirming signal — adds confluence but not raw score"
          }
        >
          {tierLabel}
        </span>
      </div>
      {describeEvidence(hit).map((line, i) => (
        <div
          key={i}
          style={{
            fontSize: 11,
            color: "var(--text-secondary)",
            lineHeight: 1.3,
          }}
        >
          {line}
        </div>
      ))}
    </div>
  );
}
