"use client";

import type { components } from "@/lib/types";

/* Top / Bottom identification copy + watch state. */
export function GrgTopBottom({
  topSide,
  botSide,
}: {
  topSide: components["schemas"]["GrgTopBottomSide"];
  botSide: components["schemas"]["GrgTopBottomSide"];
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "1fr 1fr",
        gap: 16,
        marginTop: 16,
      }}
    >
      <div className="section" data-testid="grg-top">
        <div className="section-header">
          <div className="section-title">Top Identification</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 12,
            fontSize: 12,
            color: "var(--text-secondary)",
          }}
        >
          {topSide.copy}
          <div
            style={{
              marginTop: 8,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: topSide.active ? "var(--warning)" : "var(--text-muted)",
            }}
          >
            {topSide.active ? "TOP WATCH ACTIVE" : "NO CONFIRMED TOP WATCH"}
          </div>
        </div>
      </div>
      <div className="section" data-testid="grg-bottom">
        <div className="section-header">
          <div className="section-title">Bottom Identification</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 12,
            fontSize: 12,
            color: "var(--text-secondary)",
          }}
        >
          {botSide.copy}
          <div
            style={{
              marginTop: 8,
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              color: botSide.active ? "var(--warning)" : "var(--text-muted)",
            }}
          >
            {botSide.active
              ? "BOTTOM WATCH ACTIVE"
              : "NO CONFIRMED BOTTOM WATCH"}
          </div>
        </div>
      </div>
    </div>
  );
}
