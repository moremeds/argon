"use client";

import { type GrgGate } from "@/lib/regime/useGrgLive";
import { gateColor } from "./format";

export function GatesPanel({ gates }: { gates: GrgGate[] }) {
  return (
    <div className="section" data-testid="grg-gates">
      <div className="section-header">
        <div className="section-title">Signal Gates</div>
      </div>
      <div
        className="section-body"
        style={{
          padding: 12,
          display: "flex",
          flexDirection: "column",
          gap: 8,
        }}
      >
        {gates.map((gate) => (
          <div
            key={gate.id}
            data-testid={`grg-gate-${gate.id}`}
            style={{
              display: "grid",
              gridTemplateColumns: "120px 1fr auto",
              gap: 12,
              alignItems: "center",
            }}
          >
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                letterSpacing: "1px",
                textTransform: "uppercase",
                color: "var(--text-muted)",
              }}
            >
              {gate.label}
            </span>
            <span style={{ fontSize: 12, color: "var(--text-secondary)" }}>
              {gate.copy}
            </span>
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 12,
                fontWeight: 700,
                color: gateColor(gate.status),
              }}
            >
              {gate.status}
            </span>
          </div>
        ))}
      </div>
    </div>
  );
}
