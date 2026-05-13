import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Header = TradeInsightsResponse["header"];

const badgeColor = (severity: string | undefined) => {
  if (severity === "warning") return "var(--warning)";
  if (severity === "error") return "var(--negative)";
  return "var(--accent-bg)";
};

export function TradeInsightsBiasBanner({ header }: { header: Header }) {
  return (
    <InsightPanel heading="BIAS / SETUP">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          gap: 12,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        <div>
          <div style={{ color: "var(--text-primary)", fontSize: 14 }}>
            {header.primary_setup}
          </div>
          <div style={{ color: "var(--text-secondary)" }}>
            {header.dominant_bias}
          </div>
        </div>
        <div style={{ textAlign: "right", color: "var(--text-secondary)" }}>
          <div>Confidence: {header.confidence_label}</div>
          <div>Data quality: {header.data_quality_label}</div>
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        {header.badges.map((badge) => (
          <span
            key={badge.code}
            style={{
              border: "1px solid var(--border-dim)",
              color: badgeColor(badge.severity),
              padding: "4px 8px",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
            }}
          >
            {badge.label}
          </span>
        ))}
      </div>
    </InsightPanel>
  );
}
