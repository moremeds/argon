import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";
import { AnalysisCard, type Tone, plainText } from "./ui";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;

function tidy(v: string | number | null | undefined): string {
  if (v === null || v === undefined || v === "") return "—";
  return String(v);
}

function KeyValueGrid({
  items,
}: {
  items: { label: string; value: string | number | null | undefined }[];
}) {
  return (
    <div
      style={{
        display: "grid",
        gridTemplateColumns: "repeat(auto-fit, minmax(min(100%, 120px), 1fr))",
        gap: "8px 12px",
      }}
    >
      {items.map((item) => (
        <div key={item.label}>
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 12,
              fontWeight: 700,
            }}
          >
            {item.label}
          </div>
          <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
            {plainText(tidy(item.value))}
          </div>
        </div>
      ))}
    </div>
  );
}

function triggerTone(outcome: Outcome): Tone {
  if (outcome.invalidation?.fired) return "negative";
  if (outcome.entry_trigger?.fired) return "positive";
  if (outcome.thesis_trigger?.fired) return "warning";
  return "neutral";
}

export function TriggerEvidenceCard({ outcome }: { outcome: Outcome }) {
  if (
    !outcome.thesis_trigger &&
    !outcome.entry_trigger &&
    !outcome.invalidation &&
    !outcome.anti_pin
  ) {
    return null;
  }

  return (
    <AnalysisCard
      title="Trigger State Machine & Anti-Pin"
      subtitle="v5.3 decomposed trigger components"
      tone={triggerTone(outcome)}
    >
      <div
        data-testid="ai-trigger-components"
        style={{
          display: "grid",
          gap: 6,
          fontFamily: "var(--font-mono, IBM Plex Mono, monospace)",
          fontSize: 12,
        }}
      >
        {(
          [
            ["Thesis trigger", outcome.thesis_trigger],
            ["Entry trigger", outcome.entry_trigger],
            ["Invalidation", outcome.invalidation],
          ] as const
        ).map(([label, comp], i) =>
          comp ? (
            <div
              key={`tc-${i}`}
              data-testid={`ai-trigger-${label
                .toLowerCase()
                .replace(/\s+/g, "-")}`}
              style={{
                display: "grid",
                gridTemplateColumns:
                  "minmax(108px, max-content) minmax(56px, max-content) 1fr minmax(80px, max-content)",
                gap: "0 12px",
                alignItems: "baseline",
                borderBottom: i < 2 ? "1px solid var(--border-dim)" : "none",
                paddingBottom: 4,
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
                {label}
              </div>
              <div
                style={{
                  color: "var(--text-primary)",
                  fontWeight: 600,
                }}
              >
                {comp.level?.toString() ?? "—"}
              </div>
              <div
                style={{
                  color: "var(--text-secondary)",
                  fontSize: 11,
                  overflow: "hidden",
                  textOverflow: "ellipsis",
                  whiteSpace: "nowrap",
                }}
              >
                {comp.meaning || "—"}
              </div>
              <div
                style={{
                  color: comp.fired
                    ? label === "Invalidation"
                      ? "var(--negative)"
                      : "var(--positive)"
                    : "var(--text-muted)",
                  fontSize: 10,
                  textTransform: "uppercase",
                  letterSpacing: 1.2,
                }}
              >
                {comp.fired ? "FIRED" : "pending"}
                {comp.evidence_close && comp.evidence_date ? (
                  <span
                    style={{
                      color: "var(--text-muted)",
                      marginLeft: 6,
                      fontSize: 10,
                      textTransform: "none",
                      letterSpacing: 0,
                    }}
                  >
                    @ {comp.evidence_close} ({comp.evidence_date})
                  </span>
                ) : null}
              </div>
            </div>
          ) : null,
        )}
      </div>
      {outcome.anti_pin && (
        <KeyValueGrid
          items={[
            {
              label: "Anti-pin invoked",
              value: outcome.anti_pin.invoked ? "yes" : "no",
            },
            {
              label: "Direction",
              value: outcome.anti_pin.direction ?? "none",
            },
            {
              label: "Score",
              value: `${outcome.anti_pin.score ?? 0} / ${outcome.anti_pin.max_score ?? 4}`,
            },
            {
              label: "Conviction capped",
              value: outcome.anti_pin.conviction_cap_applied ? "yes" : "no",
            },
          ]}
        />
      )}
      {outcome.anti_pin?.conditions_met &&
        outcome.anti_pin.conditions_met.length > 0 && (
          <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
            Conditions met: {outcome.anti_pin.conditions_met.join(", ")}
          </div>
        )}
      {outcome.anti_pin?.conviction_cap_applied &&
        outcome.anti_pin?.cap_reason && (
          <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
            Cap reason: {outcome.anti_pin.cap_reason}
          </div>
        )}
    </AnalysisCard>
  );
}
