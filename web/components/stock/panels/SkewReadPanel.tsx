"use client";

import { AnalyticalSeriesPanel } from "./AnalyticalSeriesPanel";

type Lean = {
  lean: string;
  confidence: string;
  basis: string;
  express: string;
};
type Read = {
  summary_line: string;
  class_context: string;
  borrow_context: string;
  earnings_gate: string;
  directional_lean: Lean;
};

function leanColor(lean: string): string {
  if (lean === "BULLISH_TILT") return "var(--positive)";
  if (lean === "BEARISH_TILT") return "var(--negative)";
  return "var(--text-muted)";
}

function leanLabel(lean: string): string {
  if (lean === "BULLISH_TILT") return "BULLISH";
  if (lean === "BEARISH_TILT") return "BEARISH";
  return "NEUTRAL";
}

export function SkewReadPanel({ read }: { read: Read }) {
  const lean = read.directional_lean;
  return (
    <AnalyticalSeriesPanel title="The Read" subtitle="DETERMINISTIC">
      <div
        style={{ color: "var(--text-primary)", fontSize: 12, lineHeight: 1.6 }}
      >
        {read.summary_line}
      </div>
      <div
        style={{
          marginTop: 12,
          paddingTop: 12,
          borderTop: "1px solid var(--border-dim)",
        }}
      >
        <div
          style={{
            fontSize: 10,
            letterSpacing: 1.5,
            textTransform: "uppercase",
            color: "var(--text-muted)",
            marginBottom: 6,
          }}
        >
          Directional Lean
        </div>
        <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
          <span
            style={{
              fontSize: 18,
              fontWeight: 700,
              color: leanColor(lean.lean),
            }}
          >
            {leanLabel(lean.lean)}
          </span>
          <span style={{ fontSize: 11, color: "var(--text-muted)" }}>
            confidence: {lean.confidence}
          </span>
        </div>
        <div
          style={{ fontSize: 11, color: "var(--text-secondary)", marginTop: 6 }}
        >
          {lean.basis}
        </div>
        {lean.express ? (
          <div
            style={{ fontSize: 11, color: "var(--text-primary)", marginTop: 6 }}
          >
            express: {lean.express}
          </div>
        ) : null}
      </div>
    </AnalyticalSeriesPanel>
  );
}
