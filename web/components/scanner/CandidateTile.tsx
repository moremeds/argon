import Link from "next/link";

import { RescanButton } from "@/components/shared/RescanButton";
import { bucketFreshness } from "@/lib/freshness";
import type { components } from "@/lib/types";

import { ContextFlagBadge } from "./ContextFlagBadge";
import { GatesIndicator } from "./GatesIndicator";
import { SignalBadge } from "./SignalBadge";

type Candidate = components["schemas"]["ScannerCandidate"];

const DOT_COLOR: Record<"fresh" | "stale" | "dead", string> = {
  fresh: "var(--positive)",
  stale: "var(--warning)",
  dead: "var(--negative)",
};

function freshnessLabel(scannedAt: string): string {
  const minutes = Math.max(
    0,
    Math.round((Date.now() - new Date(scannedAt).getTime()) / 60_000),
  );
  if (minutes < 1) return "just now";
  if (minutes < 60) return `${minutes}m ago`;
  const hours = Math.round(minutes / 60);
  return `${hours}h ago`;
}

export function CandidateTile({ candidate }: { candidate: Candidate }) {
  const freshness = bucketFreshness(candidate.scanned_at);
  return (
    <div
      style={{
        padding: 16,
        marginBottom: 8,
        backgroundColor: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
      }}
    >
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <div style={{ display: "flex", alignItems: "baseline", gap: 12 }}>
          {candidate.is_type_f ? (
            <span style={{ color: "var(--accent-warm)" }}>*</span>
          ) : null}
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 18,
              fontWeight: 700,
              color: "var(--text-primary)",
            }}
          >
            {candidate.ticker}
          </span>
          {candidate.spot ? (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 14,
                color: "var(--text-muted)",
              }}
            >
              ${candidate.spot}
            </span>
          ) : null}
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 22,
            fontWeight: 700,
            color: "var(--text-primary)",
          }}
        >
          {Number(candidate.final_score).toFixed(2)}
        </span>
      </div>
      <div style={{ marginBottom: 6 }}>
        {candidate.hits.map((h) => (
          <SignalBadge key={h.signal_type} hit={h} />
        ))}
      </div>
      <div style={{ marginBottom: 8 }}>
        {candidate.context_flags.map((f) => (
          <ContextFlagBadge key={f.layer} flag={f} />
        ))}
        <GatesIndicator gates={candidate.gates} />
      </div>
      <div
        style={{
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--text-muted)",
        }}
      >
        <span>
          <span
            style={{
              display: "inline-block",
              width: 6,
              height: 6,
              borderRadius: "50%",
              backgroundColor: DOT_COLOR[freshness],
              marginRight: 6,
            }}
          />
          scanned {freshnessLabel(candidate.scanned_at)}
        </span>
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <RescanButton ticker={candidate.ticker} initialJob={null} />
          <Link
            href={`/stock/${candidate.ticker}/trade-plan`}
            style={{
              color: "var(--accent-warm)",
              textDecoration: "none",
            }}
          >
            Evaluate →
          </Link>
        </div>
      </div>
    </div>
  );
}
