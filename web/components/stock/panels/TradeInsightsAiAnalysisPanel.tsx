"use client";

import { Fragment, useState } from "react";
import type { ReactNode } from "react";

import {
  type TradeInsightsAiAnalysisResponse,
} from "@/lib/api";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";
import {
  type PromptMetadata,
  type Provider,
  PROVIDERS,
  isInFlight,
  useAiAnalysisPolling,
} from "./tradeInsightsAi/useAiAnalysisPolling";
import { ConsensusBreakdown } from "./tradeInsightsAi/ConsensusBreakdown";
import { LegsTable } from "./tradeInsightsAi/LegsTable";
import { ProviderTabBar } from "./tradeInsightsAi/ProviderTabBar";
import { TriggerEvidenceCard } from "./tradeInsightsAi/TriggerEvidenceCard";

export { AI_ANALYSIS_POLL_MAX_MS } from "./tradeInsightsAi/useAiAnalysisPolling";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;

const labelStyle = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase" as const,
};

type Tone = "positive" | "negative" | "warning" | "neutral";
type SectionCardData = Outcome["section_cards"]["market_structure"];

// v5 directional vocabulary — the actual decision the swing trader makes.
// Kept in sync with src/uw_scan/models/trade_insights_ai.py:DirectionalBias etc.
type DirectionalBias = "LONG_DELTA" | "SHORT_DELTA" | "WAIT";
type EntryState = "ACTIVE" | "CONDITIONAL" | "NO_ENTRY";
type TradeIntent = "directional_swing" | "range_income";

const DIRECTIONAL_BIAS_TONE: Record<DirectionalBias, Tone> = {
  LONG_DELTA: "positive",
  SHORT_DELTA: "negative",
  WAIT: "warning",
};

const DIRECTIONAL_BIAS_LABEL: Record<DirectionalBias, string> = {
  LONG_DELTA: "Long-Delta",
  SHORT_DELTA: "Short-Delta",
  WAIT: "Wait",
};

const ENTRY_STATE_LABEL: Record<EntryState, string> = {
  ACTIVE: "Active",
  CONDITIONAL: "Conditional",
  NO_ENTRY: "No Entry",
};

const TRADE_INTENT_LABEL: Record<TradeIntent, string> = {
  directional_swing: "Directional Swing",
  range_income: "Range Income",
};

function toneColor(tone: Tone): string {
  if (tone === "positive") return "var(--positive)";
  if (tone === "negative") return "var(--negative)";
  if (tone === "warning") return "var(--warning)";
  return "var(--neutral)";
}

function toneFromText(value: string | null | undefined): Tone {
  const text = (value ?? "").toLowerCase();
  if (
    text.includes("bull") ||
    text.includes("buy") ||
    text.includes("positive") ||
    text.includes("break")
  ) {
    return "positive";
  }
  if (
    text.includes("bear") ||
    text.includes("sell") ||
    text.includes("negative") ||
    text.includes("blocked") ||
    text.includes("failed")
  ) {
    return "negative";
  }
  if (
    text.includes("wait") ||
    text.includes("mixed") ||
    text.includes("check") ||
    text.includes("risk")
  ) {
    return "warning";
  }
  return "neutral";
}

function tidy(value: string | number | null | undefined): string {
  if (value == null || value === "") return "None";
  const text = String(value);
  if (!/^-?\d+(\.\d+)?$/.test(text)) return text;
  const n = Number(text);
  if (!Number.isFinite(n)) return text;
  return new Intl.NumberFormat("en-US", {
    maximumFractionDigits: Math.abs(n) < 1 ? 4 : 2,
  }).format(n);
}

function shortDate(value: string | null | undefined): string {
  if (!value) return "unknown";
  return value.slice(0, 10);
}

function clipped(value: string, max = 120): string {
  if (value.length <= max) return value;
  return `${value.slice(0, max - 1).trim()}...`;
}

function plainText(value: string | null | undefined): string {
  return (value ?? "")
    .replaceAll("needs_check", "pending validation")
    .replaceAll("do_not_sell", "do not sell premium")
    .replaceAll("_", " ");
}

function scoreText(section: SectionCardData): string | null {
  if (section.score == null || section.max_score == null) return null;
  return `score ${section.score}/${section.max_score} · ${section.data_quality}`;
}

function SmallHeading({ children }: { children: ReactNode }) {
  return (
    <div
      style={{ color: "var(--text-primary)", fontSize: 12, fontWeight: 700 }}
    >
      {children}
    </div>
  );
}

function ActionButton({
  children,
  disabled,
  compact = false,
  onClick,
}: {
  children: ReactNode;
  disabled?: boolean;
  compact?: boolean;
  onClick: () => void;
}) {
  return (
    <button
      type="button"
      onClick={onClick}
      disabled={disabled}
      style={{
        justifySelf: "start",
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: disabled ? "var(--bg-panel)" : "var(--bg-base)",
        color: disabled ? "var(--text-muted)" : "var(--text-primary)",
        cursor: disabled ? "not-allowed" : "pointer",
        fontFamily: "var(--font-mono)",
        fontSize: compact ? 10 : 11,
        padding: compact ? "5px 8px" : "7px 10px",
      }}
    >
      {children}
    </button>
  );
}

function CompactNote({ label, value }: { label: string; value: string }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 8,
      }}
    >
      <SmallHeading>{label}</SmallHeading>
      <div
        style={{
          color: "var(--text-secondary)",
          fontSize: 12,
          lineHeight: 1.4,
        }}
      >
        {plainText(clipped(value, 110))}
      </div>
    </div>
  );
}

function AnalysisCard({
  title,
  subtitle,
  tone,
  children,
}: {
  title: string;
  subtitle?: string | null;
  tone: Tone;
  children: ReactNode;
}) {
  return (
    <div
      style={{
        border: `1px solid ${tone === "neutral" ? "var(--border-dim)" : toneColor(tone)}`,
        borderRadius: 4,
        background: "var(--bg-panel)",
        height: "100%",
        minHeight: 0,
        padding: "12px 14px",
        display: "flex",
        flexDirection: "column",
        gap: 8,
        overflowWrap: "anywhere",
      }}
    >
      <div>
        <div
          style={{ display: "flex", justifyContent: "space-between", gap: 10 }}
        >
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 15,
              fontWeight: 700,
              lineHeight: 1.25,
            }}
          >
            {title}
          </div>
          {tone !== "neutral" && (
            <span
              aria-label={`${tone} signal`}
              style={{
                width: 8,
                height: 8,
                marginTop: 5,
                flex: "0 0 auto",
                background: toneColor(tone),
              }}
            />
          )}
        </div>
        {subtitle && (
          <div
            style={{
              color: "var(--text-muted)",
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              marginTop: 4,
            }}
          >
            {subtitle}
          </div>
        )}
      </div>
      {children}
    </div>
  );
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

function BulletList({
  items,
  limit = 4,
}: {
  items: (string | null | undefined)[];
  limit?: number;
}) {
  const visible = items.filter(Boolean).slice(0, limit) as string[];
  if (visible.length === 0) {
    return <div style={{ color: "var(--text-muted)", fontSize: 12 }}>None</div>;
  }
  return (
    <div style={{ display: "grid", gap: 5 }}>
      {visible.map((item) => (
        <div
          key={item}
          style={{ color: "var(--text-secondary)", fontSize: 12 }}
        >
          {plainText(item)}
        </div>
      ))}
    </div>
  );
}

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
        `${item.label}: ${tidy(item.value)}${item.note ? ` · ${item.note}` : ""}`,
    ),
    ...(section.levels ?? []).map(
      (level) =>
        `${level.kind}: ${tidy(level.price)} ${tidy(level.value)}${
          level.note ? ` · ${level.note}` : ""
        }`,
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

function DirectionalBiasBadge({ bias }: { bias: DirectionalBias }) {
  const tone = DIRECTIONAL_BIAS_TONE[bias];
  const color = toneColor(tone);
  return (
    <span
      data-testid="ai-directional-bias-badge"
      data-bias={bias}
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 4,
        padding: "3px 8px",
        border: `1px solid ${color}`,
        background: `color-mix(in oklab, ${color} 12%, transparent)`,
        borderRadius: 3,
        color,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        fontWeight: 700,
        letterSpacing: 1.2,
        textTransform: "uppercase" as const,
      }}
    >
      {DIRECTIONAL_BIAS_LABEL[bias]}
    </span>
  );
}

function EntryStatePill({ state }: { state: EntryState }) {
  // ACTIVE = solid (trigger fired, ready); CONDITIONAL = outlined (needs
  // confirmation); NO_ENTRY = muted (no edge).
  const solid = state === "ACTIVE";
  const muted = state === "NO_ENTRY";
  const tone = solid ? "positive" : muted ? "neutral" : "warning";
  const color = toneColor(tone);
  return (
    <span
      data-testid="ai-entry-state-pill"
      data-state={state}
      style={{
        display: "inline-flex",
        alignItems: "center",
        padding: "3px 8px",
        border: `1px solid ${color}`,
        background: solid
          ? `color-mix(in oklab, ${color} 18%, transparent)`
          : "transparent",
        borderRadius: 999,
        color: muted ? "var(--text-muted)" : color,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        fontWeight: solid ? 700 : 600,
        letterSpacing: 1,
        textTransform: "uppercase" as const,
      }}
    >
      {ENTRY_STATE_LABEL[state]}
    </span>
  );
}

function TradeIntentTag({ intent }: { intent: TradeIntent }) {
  return (
    <span
      data-testid="ai-trade-intent-tag"
      data-intent={intent}
      style={{
        ...labelStyle,
        padding: "2px 6px",
        border: "1px solid var(--border-dim)",
        borderRadius: 2,
        color: "var(--text-secondary)",
      }}
    >
      {TRADE_INTENT_LABEL[intent]}
    </span>
  );
}

function OutcomeGrid({
  outcome,
  provider,
}: {
  outcome: Outcome;
  provider: Provider;
}) {
  const preferred = outcome.preferred_expression;
  const topMetrics = outcome.metric_cards.slice(0, 6).map((card) => ({
    label: card.label,
    value: card.value,
  }));
  const requiredChecks = (outcome.required_checks ?? []).map(
    (item) => item.check,
  );
  const conflicts = (outcome.conflicts ?? []).map((item) => item.description);
  const missing = outcome.missing_data ?? [];

  // v5 directional vocab — fall back gracefully if the field shape is
  // missing (e.g. partial Claude output that the lenient coercer back-
  // filled with conservative defaults; the badge still renders WAIT).
  const directionalBias = outcome.headline.directional_bias as DirectionalBias;
  const entryState = outcome.headline.entry_state as EntryState;
  const tradeIntent = outcome.headline.trade_intent as TradeIntent;
  const biasFrameColor = toneColor(DIRECTIONAL_BIAS_TONE[directionalBias]);

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div
        style={{
          border: `1px solid ${biasFrameColor}`,
          borderRadius: 4,
          padding: "14px 16px",
          background: "var(--bg-panel)",
        }}
      >
        <div
          style={{
            display: "flex",
            gap: 8,
            alignItems: "center",
            flexWrap: "wrap",
          }}
        >
          <DirectionalBiasBadge bias={directionalBias} />
          <EntryStatePill state={entryState} />
          <TradeIntentTag intent={tradeIntent} />
          <div style={{ ...labelStyle, marginLeft: "auto" }}>
            {outcome.ticker} AI Analysis
          </div>
        </div>
        <div
          style={{
            color: "var(--text-primary)",
            fontSize: 16,
            fontWeight: 700,
            lineHeight: 1.25,
            marginTop: 8,
          }}
        >
          {outcome.headline.title}
        </div>
        <div
          style={{
            color: "var(--text-primary)",
            fontSize: 13,
            fontWeight: 600,
            lineHeight: 1.45,
            marginTop: 8,
          }}
        >
          {plainText(
            outcome.dominant_read?.summary ?? outcome.headline.top_reason,
          )}
        </div>
        <KeyValueGrid
          items={[
            // v5: directional_bias is the gate (rendered as badge above).
            // underlying_path is the path inference; dte_band is the band
            // pick from Step 5. stance_label kept as the legacy display
            // string so the analyst-vocabulary (e.g. "BUY setup") still
            // surfaces alongside the new fields.
            {
              label: "Path",
              value: outcome.headline.underlying_path.replace(/_/g, " "),
            },
            {
              label: "DTE Band",
              value: outcome.headline.dte_band,
            },
            {
              label: "Score",
              value: `${outcome.headline.score}/${outcome.headline.score_scale}`,
            },
            {
              label: "Conviction",
              value: `${outcome.headline.conviction} · ${outcome.headline.conviction_label}`,
            },
            {
              label: "Data",
              value: `${outcome.snapshot.freshness_label} · ${shortDate(outcome.snapshot.data_as_of)}`,
            },
            ...topMetrics,
          ]}
        />
        <div
          style={{
            display: "grid",
            gridTemplateColumns:
              "repeat(auto-fit, minmax(min(100%, 240px), 1fr))",
            gap: 8,
            marginTop: 10,
          }}
        >
          <CompactNote
            label="Primary Risk"
            value={outcome.headline.primary_risk}
          />
          <CompactNote
            label="Trigger To Watch"
            value={outcome.headline.watch_trigger}
          />
        </div>
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: 12,
            fontWeight: 700,
            marginTop: 10,
          }}
        >
          Generated analysis from local {providerLabel(provider)} ·{" "}
          {outcome.analysis_produced_at.slice(0, 10)} · Not financial advice
        </div>
      </div>

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
                outcome.vrp_assessment?.summary ??
                  "No VRP assessment supplied.",
              )}
            </div>
            {outcome.vrp_assessment?.metrics?.length ? (
              <KeyValueGrid
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
          <AnalysisCard
            title="Trade Setup Readiness"
            subtitle={
              preferred
                ? preferred.title
                : "No trade structure cleared validation"
            }
            tone={toneFromText(preferred?.status_observed)}
          >
            {preferred ? (
              <>
                <KeyValueGrid
                  items={[
                    { label: "Structure", value: preferred.structure },
                    { label: "Entry", value: preferred.estimated_entry },
                    {
                      label: "Max Profit",
                      value: preferred.max_profit_observed,
                    },
                    { label: "Max Loss", value: preferred.max_loss_observed },
                    { label: "R:R", value: preferred.reward_risk },
                    { label: "Status", value: preferred.status_observed },
                  ]}
                />
                {preferred.strike_role && (
                  <KeyValueGrid
                    items={[
                      {
                        label: "Trigger",
                        value: preferred.strike_role.trigger_level || "—",
                      },
                      {
                        label: "Target",
                        value: preferred.strike_role.target_level || "—",
                      },
                      {
                        label: "Invalidate",
                        value: preferred.strike_role.invalid_level || "—",
                      },
                      {
                        label: "Long leg",
                        value: preferred.strike_role.long_leg_role || "n/a",
                      },
                      {
                        label: "Short leg",
                        value: preferred.strike_role.short_leg_role || "n/a",
                      },
                    ]}
                  />
                )}
                {preferred.legs && <LegsTable legs={preferred.legs} />}
                <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
                  {plainText(preferred.why)}
                </div>
                <BulletList
                  items={preferred.management_notes ?? []}
                  limit={3}
                />
              </>
            ) : (
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
                No entry candidate is ready yet. The generated structures stay
                pending validation until the checklist passes.
              </div>
            )}
          </AnalysisCard>
          <TriggerEvidenceCard outcome={outcome} />
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
              <BulletList items={[...conflicts, ...missing]} limit={3} />
            </div>
          </AnalysisCard>
        </div>
      </div>
    </div>
  );
}

function providerLabel(p: Provider): string {
  return p.charAt(0).toUpperCase() + p.slice(1);
}

function isLegacyAnalysis(
  analysis: TradeInsightsAiAnalysisResponse | null,
  currentPromptVersion: string,
): boolean {
  if (!analysis) return false;
  if (analysis.status !== "succeeded") return false;
  if (!currentPromptVersion) return false;
  // The v5 API-side legacy guard (_row_to_ai_response) drops outcome to null
  // when the row's prompt_version differs from the current PROMPT_VERSION,
  // so we recognize a legacy row by the (succeeded + null outcome +
  // prompt_version mismatch) signature.
  return (
    analysis.outcome == null &&
    analysis.prompt_version !== currentPromptVersion
  );
}

function currentPromptDisplay(metadata: PromptMetadata): string {
  return (
    metadata.current_prompt_label ||
    metadata.current_prompt_version ||
    "current prompt"
  );
}

function ProviderTabBody({
  provider,
  analysis,
  pending,
  promptMetadata,
}: {
  provider: Provider;
  analysis: TradeInsightsAiAnalysisResponse | null;
  pending: boolean;
  promptMetadata: PromptMetadata;
}) {
  const succeeded = analysis?.status === "succeeded" && analysis.outcome;
  const failed = analysis?.status === "failed";
  const legacy = isLegacyAnalysis(
    analysis,
    promptMetadata.current_prompt_version,
  );
  return (
    <div style={{ display: "grid", gap: 12 }}>
      {pending && (
        <InsightStatusBanner
          text={`${providerLabel(provider)} is running…`}
          severity="info"
        />
      )}
      {analysis && isInFlight(analysis) && !pending && (
        <InsightStatusBanner
          text={`${providerLabel(provider)} ${analysis.status}`}
          severity="info"
        />
      )}
      {failed && (
        <InsightStatusBanner
          text={analysis?.error_message ?? `${providerLabel(provider)} failed`}
          severity="negative"
        />
      )}
      {legacy && (
        <InsightStatusBanner
          text={
            `Legacy analysis (${analysis?.prompt_version}). Schema bumped ` +
            `to ${currentPromptDisplay(promptMetadata)} — click Run to ` +
            `regenerate with the current prompt contract.`
          }
          severity="warning"
        />
      )}
      {succeeded && analysis.outcome && (
        <OutcomeGrid outcome={analysis.outcome} provider={provider} />
      )}
      {!analysis && !pending && (
        <div
          style={{
            color: "var(--text-secondary)",
            fontSize: 12,
            padding: 12,
            border: "1px dashed var(--border-dim)",
            borderRadius: 4,
          }}
        >
          No analysis yet for {providerLabel(provider)}. Click Run to generate.
        </div>
      )}
      {analysis?.status === "succeeded" && (
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: 10,
            fontFamily: "var(--font-mono)",
            letterSpacing: 0.5,
          }}
        >
          Generated by {providerLabel(provider)} ({analysis.model}) · prompt{" "}
          {analysis.prompt_version} ·{" "}
          {shortDate(analysis.produced_at ?? analysis.finished_at)}
        </div>
      )}
    </div>
  );
}

export function TradeInsightsAiAnalysisPanel({ ticker }: { ticker: string }) {
  const [active, setActive] = useState<Provider>("codex");
  const {
    actionLabel,
    allPending,
    canRun,
    consensusForTicker,
    forceRun,
    latestForTicker,
    loadingForTicker,
    pendingIdsForTicker,
    promptMetadataForTicker,
    run,
    unavailableForTicker,
  } = useAiAnalysisPolling(ticker);
  return (
    <InsightPanel
      heading="AI ANALYSIS"
      action={
        canRun ? (
          <ActionButton
            compact
            onClick={() => run(forceRun)}
            disabled={loadingForTicker || allPending}
          >
            {actionLabel}
          </ActionButton>
        ) : undefined
      }
    >
      <div style={{ display: "grid", gap: 12 }}>
        {unavailableForTicker && (
          <InsightStatusBanner
            text="Local AI analysis is not enabled for this environment."
            severity="info"
          />
        )}
        {consensusForTicker &&
          consensusForTicker.consensus_grade &&
          consensusForTicker.consensus_grade !== "missing" && (
            <div
              data-testid="ai-provider-consensus"
              style={{
                border: "1px solid var(--border-dim)",
                borderRadius: 4,
                padding: "8px 10px",
                background:
                  consensusForTicker.consensus_grade === "full"
                    ? "var(--bg-panel)"
                    : "var(--bg-base)",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                color: "var(--text-primary)",
              }}
            >
              <span
                style={{
                  color:
                    consensusForTicker.consensus_grade === "full"
                      ? "var(--positive)"
                      : consensusForTicker.consensus_grade === "divergent"
                        ? "var(--negative)"
                        : "var(--warning)",
                  fontWeight: 600,
                  letterSpacing: 1.2,
                  textTransform: "uppercase",
                  marginRight: 8,
                }}
              >
                Consensus: {consensusForTicker.consensus_grade}
              </span>
              {consensusForTicker.actionable_disagreement && (
                <span style={{ color: "var(--text-secondary)" }}>
                  {consensusForTicker.actionable_disagreement}
                </span>
              )}
            </div>
          )}
        <ConsensusBreakdown
          codex={latestForTicker.codex}
          claude={latestForTicker.claude}
        />
        <ProviderTabBar
          active={active}
          latest={latestForTicker}
          pendingIds={pendingIdsForTicker}
          providers={PROVIDERS}
          setActive={setActive}
        />
        <ProviderTabBody
          provider={active}
          analysis={latestForTicker[active]}
          pending={Boolean(pendingIdsForTicker[active])}
          promptMetadata={promptMetadataForTicker}
        />
      </div>
    </InsightPanel>
  );
}
