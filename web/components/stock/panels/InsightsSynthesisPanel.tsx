import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Synthesis = TradeInsightsResponse["synthesis"];

function ListBlock({ title, items }: { title: string; items: string[] }) {
  return (
    <div style={{ display: "grid", gap: 5, minWidth: 220, maxWidth: 360 }}>
      <div
        style={{
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          textTransform: "uppercase",
        }}
      >
        {title}
      </div>
      {items.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>None</div>
      ) : (
        <div style={{ display: "grid", gap: 5 }}>
          {items.map((item) => (
            <div
              key={item}
              style={{
                color: "var(--text-secondary)",
                fontSize: 12,
                lineHeight: 1.35,
              }}
            >
              {item}
            </div>
          ))}
        </div>
      )}
    </div>
  );
}

export function InsightsSynthesisPanel({
  synthesis,
}: {
  synthesis: Synthesis;
}) {
  return (
    <InsightPanel heading="SYNTHESIS" subheading={synthesis.dominant_story}>
      <div style={{ display: "grid", gap: 14 }}>
        <div
          style={{
            display: "flex",
            flexWrap: "wrap",
            alignItems: "start",
            gap: "16px 34px",
          }}
        >
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(2, minmax(120px, max-content))",
              gap: 16,
              fontFamily: "var(--font-mono)",
              fontSize: 12,
            }}
          >
            <div>
              <div style={{ color: "var(--text-muted)", fontSize: 10 }}>
                Preferred
              </div>
              <div style={{ color: "var(--text-primary)" }}>
                {synthesis.preferred_idea_id ?? "None"}
              </div>
            </div>
            <div>
              <div style={{ color: "var(--text-muted)", fontSize: 10 }}>
                Best risk/reward
              </div>
              <div style={{ color: "var(--text-primary)" }}>
                {synthesis.best_risk_reward_idea_id ?? "None"}
              </div>
            </div>
          </div>
          <ListBlock title="Avoid" items={synthesis.avoid} />
          <ListBlock
            title="Required before sizing"
            items={synthesis.required_before_sizing}
          />
        </div>
      </div>
    </InsightPanel>
  );
}
