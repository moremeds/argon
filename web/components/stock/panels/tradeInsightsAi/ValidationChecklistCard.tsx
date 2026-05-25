import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";
import {
  AnalysisCard,
  BulletList,
  SmallHeading,
  clipped,
  plainText,
} from "./ui";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;

function ScenarioList({ cards }: { cards: Outcome["scenario_cards"] }) {
  const visible = cards.slice(0, 3);
  if (visible.length === 0) {
    return <div style={{ color: "var(--text-muted)", fontSize: 12 }}>None</div>;
  }
  return (
    <div style={{ display: "grid", gap: 5 }}>
      {visible.map((card) => (
        <div key={card.case}>
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {card.title}
          </div>
          <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
            {plainText(clipped(card.description, 96))}
          </div>
        </div>
      ))}
    </div>
  );
}

export function ValidationChecklistCard({
  outcome,
  requiredChecks,
  blockers,
}: {
  outcome: Outcome;
  requiredChecks: string[];
  blockers: string[];
}) {
  return (
    <AnalysisCard
      title="Validation Checklist"
      subtitle="What must be watched or confirmed"
      tone="warning"
    >
      <div>
        <SmallHeading>Price paths to watch</SmallHeading>
        <ScenarioList cards={outcome.scenario_cards} />
      </div>
      <div>
        <SmallHeading>Must confirm before sizing</SmallHeading>
        <BulletList items={requiredChecks} limit={3} />
      </div>
      <div>
        <SmallHeading>Why still blocked</SmallHeading>
        <BulletList items={blockers} limit={3} />
      </div>
    </AnalysisCard>
  );
}
