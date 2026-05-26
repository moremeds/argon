import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";
import { ReadinessCard } from "./ReadinessCard";
import { TriggerEvidenceCard } from "./TriggerEvidenceCard";
import { ValidationChecklistCard } from "./ValidationChecklistCard";
import {
  AnalysisCard,
  BulletList,
  ProviderKeyValueGrid,
  SmallHeading,
  type Tone,
  plainText,
  tidyProviderValue,
} from "./ui";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;
type SectionCardData = Outcome["section_cards"]["market_structure"];

function scoreText(section: SectionCardData): string | null {
  if (section.score == null || section.max_score == null) return null;
  return `score ${section.score}/${section.max_score} · ${section.data_quality}`;
}

function SectionSummaryCard({
  section,
  tone,
}: {
  section: SectionCardData;
  tone: Tone;
}) {
  const highlights = [
    ...(section.highlights ?? []).map(
      (item) =>
        `${item.label}: ${tidyProviderValue(item.value)}${
          item.note ? ` · ${item.note}` : ""
        }`,
    ),
    ...(section.levels ?? []).map(
      (level) =>
        `${level.kind}: ${tidyProviderValue(level.price)} ${tidyProviderValue(
          level.value,
        )}${level.note ? ` · ${level.note}` : ""}`,
    ),
  ];
  return (
    <AnalysisCard
      title={section.title}
      subtitle={scoreText(section)}
      tone={tone}
    >
      <div
        style={{
          color: "var(--text-primary)",
          fontSize: 13,
          fontWeight: 600,
          lineHeight: 1.45,
        }}
      >
        {plainText(section.summary)}
      </div>
      <BulletList items={highlights} />
    </AnalysisCard>
  );
}

export function SectionCardsGrid({
  outcome,
  toneFromText,
}: {
  outcome: Outcome;
  toneFromText: (value: string | null | undefined) => Tone;
}) {
  const preferred = outcome.preferred_expression;
  const requiredChecks = (outcome.required_checks ?? []).map(
    (item) => item.check,
  );
  const conflicts = (outcome.conflicts ?? []).map((item) => item.description);
  const missing = outcome.missing_data ?? [];

  return (
    <div
      data-testid="ai-analysis-card-grid"
      style={{
        display: "grid",
        gap: 12,
      }}
    >
      <div
        data-testid="ai-analysis-upper-card-grid"
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
          alignItems: "stretch",
          gap: 12,
        }}
      >
        <SectionSummaryCard
          section={outcome.section_cards.market_structure}
          tone={toneFromText(outcome.section_cards.market_structure.summary)}
        />
        <SectionSummaryCard
          section={outcome.section_cards.volatility}
          tone={toneFromText(outcome.section_cards.volatility.summary)}
        />
        <SectionSummaryCard
          section={outcome.section_cards.flow_positioning}
          tone={toneFromText(outcome.section_cards.flow_positioning.summary)}
        />
      </div>
      <div
        data-testid="ai-analysis-lower-card-grid"
        style={{
          display: "grid",
          gridTemplateColumns:
            "repeat(auto-fit, minmax(min(100%, 260px), 1fr))",
          alignItems: "stretch",
          gap: 12,
        }}
      >
        <AnalysisCard
          title={outcome.vrp_assessment?.title ?? "VRP Assessment"}
          subtitle="Vol premium edge and blockers"
          tone={toneFromText(outcome.vrp_assessment?.signal)}
        >
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 13,
              fontWeight: 600,
              lineHeight: 1.45,
            }}
          >
            {plainText(
              outcome.vrp_assessment?.summary ?? "No VRP assessment supplied.",
            )}
          </div>
          {outcome.vrp_assessment?.metrics?.length ? (
            <ProviderKeyValueGrid
              items={outcome.vrp_assessment.metrics
                .slice(0, 6)
                .map((metric) => ({
                  label: metric.label,
                  value: metric.value,
                }))}
            />
          ) : null}
          {requiredChecks.length > 0 && (
            <div>
              <SmallHeading>Checks blocking action</SmallHeading>
              <BulletList items={requiredChecks} limit={3} />
            </div>
          )}
          {outcome.vrp_assessment?.reason && (
            <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
              {plainText(outcome.vrp_assessment.reason)}
            </div>
          )}
        </AnalysisCard>
        <ReadinessCard preferred={preferred} toneFromText={toneFromText} />
        <TriggerEvidenceCard outcome={outcome} />
        <ValidationChecklistCard
          outcome={outcome}
          requiredChecks={requiredChecks}
          blockers={[...conflicts, ...missing]}
        />
      </div>
    </div>
  );
}
