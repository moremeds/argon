import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Synthesis = TradeInsightsResponse["synthesis"];

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div>
      <div
        style={{
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          textTransform: "uppercase",
          marginBottom: 4,
        }}
      >
        {title}
      </div>
      <ul
        style={{
          margin: 0,
          paddingLeft: 18,
          color: "var(--text-secondary)",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        {items.map((item) => (
          <li key={item}>{item}</li>
        ))}
      </ul>
    </div>
  );
}

export function InsightsSynthesisPanel({ synthesis }: { synthesis: Synthesis }) {
  return (
    <InsightPanel heading="SYNTHESIS / NEXT CHECKS">
      <div style={{ display: "grid", gap: 12 }}>
        <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
          {synthesis.dominant_story}
        </div>
        <div
          style={{
            display: "grid",
            gridTemplateColumns: "1fr 1fr",
            gap: 12,
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--text-secondary)",
          }}
        >
          <div>Preferred: {synthesis.preferred_idea_id ?? "None"}</div>
          <div>Best risk/reward: {synthesis.best_risk_reward_idea_id ?? "None"}</div>
        </div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
          <ListBlock title="Avoid" items={synthesis.avoid} />
          <ListBlock title="Required before sizing" items={synthesis.required_before_sizing} />
        </div>
      </div>
    </InsightPanel>
  );
}
