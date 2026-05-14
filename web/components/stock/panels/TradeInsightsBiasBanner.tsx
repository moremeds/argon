import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Header = TradeInsightsResponse["header"];

const badgeColor = (severity: string | undefined) => {
  if (severity === "warning") return "var(--warning)";
  if (severity === "error") return "var(--negative)";
  return "var(--accent-bg)";
};

const readable = (value: string | null | undefined) =>
  (value ?? "Unknown")
    .toLowerCase()
    .replaceAll("_", " ")
    .replace(/\b\w/g, (letter) => letter.toUpperCase());

export function TradeInsightsBiasBanner({ header }: { header: Header }) {
  return (
    <InsightPanel heading="RESEARCH READ">
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(0, 1fr) auto",
          gap: 18,
          alignItems: "start",
        }}
      >
        <div style={{ display: "grid", gap: 5 }}>
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 18,
              fontWeight: 700,
              lineHeight: 1.25,
            }}
          >
            {readable(header.primary_setup)}
          </div>
          <div style={{ color: "var(--text-secondary)", fontSize: 13 }}>
            {readable(header.dominant_bias)}
          </div>
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "repeat(2, max-content)",
            gap: 8,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          <div style={{ color: "var(--text-muted)" }}>Confidence</div>
          <div style={{ color: "var(--text-primary)", textAlign: "right" }}>
            {readable(header.confidence_label)}
          </div>
          <div style={{ color: "var(--text-muted)" }}>Data quality</div>
          <div style={{ color: "var(--text-primary)", textAlign: "right" }}>
            {readable(header.data_quality_label)}
          </div>
        </div>
      </div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8, marginTop: 2 }}>
        {header.badges.map((badge) => (
          <span
            key={badge.code}
            style={{
              border: "1px solid var(--border-dim)",
              color: badgeColor(badge.severity),
              background: "var(--bg-base)",
              padding: "5px 8px",
              fontFamily: "var(--font-mono)",
              fontSize: 11,
              lineHeight: 1,
            }}
          >
            {badge.label}
          </span>
        ))}
      </div>
    </InsightPanel>
  );
}
