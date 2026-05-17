import type { components } from "@/lib/types";

import { PostureChip, type PostureState } from "../chips/PostureChip";

import { ValuationFlagCard } from "./ValuationFlagCard";
import { ValuationPostureText } from "./ValuationPostureText";

type V = components["schemas"]["GoldValuationPostureModel"];

export function ValuationPanel({ valuation }: { valuation: V }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 16 }}>
      <div
        style={{
          display: "flex",
          alignItems: "baseline",
          gap: 12,
          justifyContent: "space-between",
        }}
      >
        <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
          <h2
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              letterSpacing: 1.8,
              textTransform: "uppercase",
              color: "var(--text-primary, #cfd2db)",
              margin: 0,
            }}
          >
            LENS 3 · VALUATION OVERLAY
          </h2>
          <PostureChip
            state={(valuation.posture_chip ?? "NEUTRAL") as PostureState}
          />
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--warning, #f5a623)",
          }}
        >
          ⚠ NEVER A SIZING INPUT
        </span>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
          gap: 12,
        }}
      >
        <ValuationFlagCard valuation={valuation} />
        <div
          style={{
            padding: 16,
            background: "var(--bg-panel, #0d1018)",
            border: "1px solid var(--border-dim, #1b2030)",
            borderRadius: 4,
            display: "flex",
            flexDirection: "column",
            gap: 8,
          }}
        >
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              letterSpacing: 1.5,
              textTransform: "uppercase",
              color: "var(--text-muted, #6b7280)",
            }}
          >
            MEAN-REVERSION RISK
          </span>
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: "var(--text-secondary, #9aa3b2)",
              lineHeight: 1.5,
            }}
          >
            Context only. Flag identifies tail risk against historical anchors;
            sizing decisions remain with Lens 1 structural posture.
          </span>
        </div>
      </div>

      <ValuationPostureText valuation={valuation} />
    </div>
  );
}
