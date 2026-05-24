import { Fragment } from "react";

import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;
type PreferredExpression = NonNullable<Outcome["preferred_expression"]>;
type Legs = NonNullable<PreferredExpression["legs"]>;

function SmallHeading({ children }: { children: string }) {
  return (
    <div
      style={{ color: "var(--text-primary)", fontSize: 12, fontWeight: 700 }}
    >
      {children}
    </div>
  );
}

export function LegsTable({ legs }: { legs: Legs }) {
  if (legs.length === 0) return null;

  return (
    <div data-testid="ai-preferred-legs">
      <SmallHeading>Option Legs (v5.3)</SmallHeading>
      <div
        style={{
          display: "grid",
          gridTemplateColumns:
            "minmax(60px, max-content) minmax(60px, max-content) 1fr minmax(96px, max-content)",
          gap: "4px 12px",
          fontFamily: "var(--font-mono, IBM Plex Mono, monospace)",
          fontSize: 12,
        }}
      >
        <div
          style={{
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: 1.5,
            fontSize: 10,
          }}
        >
          Side
        </div>
        <div
          style={{
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: 1.5,
            fontSize: 10,
          }}
        >
          Type
        </div>
        <div
          style={{
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: 1.5,
            fontSize: 10,
          }}
        >
          Strike
        </div>
        <div
          style={{
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: 1.5,
            fontSize: 10,
          }}
        >
          Expiry
        </div>
        {legs.map((leg, i) => (
          <Fragment key={`leg-${i}`}>
            <div
              style={{
                color:
                  leg.side === "long" ? "var(--positive)" : "var(--negative)",
              }}
            >
              {leg.side}
            </div>
            <div style={{ color: "var(--text-primary)" }}>
              {leg.option_type}
            </div>
            <div style={{ color: "var(--text-primary)" }}>{leg.strike}</div>
            <div style={{ color: "var(--text-secondary)" }}>{leg.expiry}</div>
          </Fragment>
        ))}
      </div>
    </div>
  );
}
