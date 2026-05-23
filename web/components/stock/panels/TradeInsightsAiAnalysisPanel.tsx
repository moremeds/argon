"use client";

import { useCallback, useEffect, useRef, useState } from "react";
import type { ReactNode } from "react";

import { api, type TradeInsightsAiAnalysisResponse } from "@/lib/api";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;
export const AI_ANALYSIS_POLL_MAX_MS = 10 * 60 * 1000;

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

function isInFlight(analysis: TradeInsightsAiAnalysisResponse): boolean {
  return analysis.status === "queued" || analysis.status === "running";
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
          {(outcome.trigger_evidence || outcome.anti_pin) && (
            <AnalysisCard
              title="Trigger Evidence & Anti-Pin"
              subtitle="v5.2 deterministic state proofs"
              tone={
                outcome.trigger_evidence?.trigger_fired ? "positive" : "warning"
              }
            >
              {outcome.trigger_evidence && (
                <KeyValueGrid
                  items={[
                    {
                      label: "Trigger fired",
                      value: outcome.trigger_evidence.trigger_fired
                        ? "yes"
                        : "no",
                    },
                    {
                      label: "Trigger type",
                      value: outcome.trigger_evidence.trigger_type ?? "unknown",
                    },
                    {
                      label: "Latest close",
                      value:
                        outcome.trigger_evidence.evidence_close?.toString() ??
                        "—",
                    },
                    {
                      label: "Close date",
                      value:
                        outcome.trigger_evidence.evidence_close_date?.toString() ??
                        "—",
                    },
                    {
                      label: "Trigger level",
                      value:
                        outcome.trigger_evidence.trigger_level?.toString() ??
                        "—",
                    },
                  ]}
                />
              )}
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
                      value: outcome.anti_pin.conviction_cap_applied
                        ? "yes"
                        : "no",
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
          )}
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

type Provider = "codex" | "claude";
const PROVIDERS: readonly Provider[] = ["codex", "claude"] as const;

function providerLabel(p: Provider): string {
  return p.charAt(0).toUpperCase() + p.slice(1);
}

function stateBadge(
  analysis: TradeInsightsAiAnalysisResponse | null,
  pending: boolean,
): string {
  if (pending) return "◐"; // running
  if (!analysis) return "○"; // empty
  if (analysis.status === "succeeded") return "●";
  if (analysis.status === "failed") return "✕";
  return "○";
}

// Current prompt version — used by the legacy-row detector below. Kept in
// sync with src/uw_scan/reports/trade_insights_ai.py:PROMPT_VERSION. The
// detector compares against this string; any prior version (v4, v5)
// renders the "legacy — re-run" banner so users see what the API guard
// already did (dropped outcome to null).
const CURRENT_PROMPT_VERSION = "trade-insights-ai-v5.2";

function isLegacyAnalysis(
  analysis: TradeInsightsAiAnalysisResponse | null,
): boolean {
  if (!analysis) return false;
  if (analysis.status !== "succeeded") return false;
  // The v5 API-side legacy guard (_row_to_ai_response) drops outcome to null
  // when the row's prompt_version differs from the current PROMPT_VERSION,
  // so we recognize a legacy row by the (succeeded + null outcome +
  // prompt_version mismatch) signature.
  return (
    analysis.outcome == null &&
    analysis.prompt_version !== CURRENT_PROMPT_VERSION
  );
}

function ProviderTabBody({
  provider,
  analysis,
  pending,
}: {
  provider: Provider;
  analysis: TradeInsightsAiAnalysisResponse | null;
  pending: boolean;
}) {
  const succeeded = analysis?.status === "succeeded" && analysis.outcome;
  const failed = analysis?.status === "failed";
  const legacy = isLegacyAnalysis(analysis);
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
            `to ${CURRENT_PROMPT_VERSION} — click Run to regenerate with the ` +
            `v5.2 prompt (active-trigger evidence, thesis archetype, ` +
            `strict strike_role, anti-pin scope).`
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
  const [latest, setLatest] = useState<{
    codex: TradeInsightsAiAnalysisResponse | null;
    claude: TradeInsightsAiAnalysisResponse | null;
  }>({ codex: null, claude: null });
  // v5.2: cross-provider consensus computed at GET /latest time.
  // Rendered as a chip above the tabs so the operator sees agreement /
  // actionable disagreement at-a-glance.
  const [consensus, setConsensus] = useState<{
    consensus_grade?: string;
    actionable_disagreement?: string;
  } | null>(null);
  const [pendingIds, setPendingIds] = useState<{
    codex: string | null;
    claude: string | null;
  }>({ codex: null, claude: null });
  const [active, setActive] = useState<Provider>("codex");
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const requestTokenRef = useRef(0);

  const pollOne = useCallback(
    async (provider: Provider, analysisId: string, token: number) => {
      const isCurrentRequest = () => requestTokenRef.current === token;
      let current: TradeInsightsAiAnalysisResponse;
      try {
        current = await api.tradeInsightsAiAnalysisStatus(ticker, analysisId);
      } catch (err) {
        if (!isCurrentRequest()) return;
        if (String(err).includes("503")) {
          setUnavailable(true);
        }
        return;
      }
      if (!isCurrentRequest()) return;
      let elapsedMs = 0;
      const intervalMs = 3000;
      const maxMs = AI_ANALYSIS_POLL_MAX_MS;
      while (isInFlight(current)) {
        if (elapsedMs >= maxMs) break;
        await new Promise((r) => setTimeout(r, intervalMs));
        if (!isCurrentRequest()) return;
        elapsedMs += intervalMs;
        try {
          current = await api.tradeInsightsAiAnalysisStatus(ticker, analysisId);
        } catch (err) {
          if (!isCurrentRequest()) return;
          if (String(err).includes("503")) {
            setUnavailable(true);
          }
          return;
        }
        if (!isCurrentRequest()) return;
      }
      // Terminal — refresh latest pair to pull full payload + clear pending slot.
      try {
        const pair = await api.tradeInsightsAiAnalysisLatest(ticker);
        if (!isCurrentRequest()) return;
        setLatest({ codex: pair.codex ?? null, claude: pair.claude ?? null });
        setConsensus(pair.provider_consensus ?? null);
      } catch {
        // tolerate /latest hiccups — at minimum overlay the in-flight state.
        if (isCurrentRequest()) {
          setLatest((prev) => ({ ...prev, [provider]: current }));
        }
      }
      setPendingIds((prev) => ({ ...prev, [provider]: null }));
    },
    [ticker],
  );

  useEffect(() => {
    const token = ++requestTokenRef.current;
    setLatest({ codex: null, claude: null });
    setPendingIds({ codex: null, claude: null });
    setLoading(false);
    setUnavailable(false);
    let cancelled = false;
    void (async () => {
      try {
        const pair = await api.tradeInsightsAiAnalysisLatest(ticker);
        if (!cancelled && requestTokenRef.current === token) {
          setLatest({ codex: pair.codex ?? null, claude: pair.claude ?? null });
          setConsensus(pair.provider_consensus ?? null);
        }
      } catch (err) {
        if (
          !cancelled &&
          requestTokenRef.current === token &&
          String(err).includes("503")
        ) {
          setUnavailable(true);
        }
      }
    })();
    return () => {
      cancelled = true;
      requestTokenRef.current += 1;
    };
  }, [ticker]);

  async function run(force_rerun = false) {
    const token = ++requestTokenRef.current;
    const isCurrentRequest = () => requestTokenRef.current === token;
    setLoading(true);
    setUnavailable(false);
    // Skip providers that already have an in-flight row — a hung codex must
    // not block re-running claude. Backend mirrors this filter server-side.
    const providersToRun: Provider[] = PROVIDERS.filter((p) => !pendingIds[p]);
    if (providersToRun.length === 0) {
      setLoading(false);
      return;
    }
    try {
      const body: { force_rerun?: boolean; providers?: Provider[] } = {};
      if (force_rerun) body.force_rerun = true;
      if (providersToRun.length < PROVIDERS.length)
        body.providers = providersToRun;
      const resp = await api.tradeInsightsAiAnalysis(ticker, body);
      if (!isCurrentRequest()) return;
      const newPending: { codex: string | null; claude: string | null } = {
        codex: pendingIds.codex,
        claude: pendingIds.claude,
      };
      for (const stub of resp.analyses) {
        if (stub.status === "succeeded" && stub.reused) {
          newPending[stub.provider as Provider] = null;
          continue;
        }
        newPending[stub.provider as Provider] = stub.analysis_id;
      }
      setPendingIds(newPending);
      // Refresh latest now so any reused-succeeded rows appear immediately.
      try {
        const pair = await api.tradeInsightsAiAnalysisLatest(ticker);
        if (isCurrentRequest()) {
          setLatest({
            codex: pair.codex ?? null,
            claude: pair.claude ?? null,
          });
        }
      } catch {
        /* tolerate */
      }
      // Release the submit gate as soon as the POST + /latest roundtrip is
      // done — polls run in the background so the Run button can re-enable
      // for providers that finish early. Pending-set semantics now drive
      // disabled state via allPending.
      if (isCurrentRequest()) setLoading(false);
      for (const p of PROVIDERS) {
        const id = newPending[p];
        if (id) void pollOne(p, id, token);
      }
    } catch (err) {
      if (!isCurrentRequest()) return;
      if (String(err).includes("503")) {
        setUnavailable(true);
      }
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }

  const anyPending = Boolean(pendingIds.codex || pendingIds.claude);
  const allPending = Boolean(pendingIds.codex && pendingIds.claude);
  const anyFailed =
    latest.codex?.status === "failed" || latest.claude?.status === "failed";
  const anySucceeded =
    latest.codex?.status === "succeeded" ||
    latest.claude?.status === "succeeded";
  // Only block Run when EVERY provider is pending — a hung codex tab should
  // not prevent re-running claude. Server-side mirror filters the POST.
  const canRun = !unavailable && !allPending;
  const forceRun = anySucceeded || anyFailed;
  const actionLabel = loading || allPending ? "Running…" : "Run Analysis";
  return (
    <InsightPanel
      heading="AI ANALYSIS"
      action={
        canRun ? (
          <ActionButton
            compact
            onClick={() => run(forceRun)}
            disabled={loading || allPending}
          >
            {actionLabel}
          </ActionButton>
        ) : undefined
      }
    >
      <div style={{ display: "grid", gap: 12 }}>
        {unavailable && (
          <InsightStatusBanner
            text="Local AI analysis is not enabled for this environment."
            severity="info"
          />
        )}
        {consensus &&
          consensus.consensus_grade &&
          consensus.consensus_grade !== "missing" && (
            <div
              data-testid="ai-provider-consensus"
              style={{
                border: "1px solid var(--border-dim)",
                borderRadius: 4,
                padding: "8px 10px",
                background:
                  consensus.consensus_grade === "full"
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
                    consensus.consensus_grade === "full"
                      ? "var(--positive)"
                      : consensus.consensus_grade === "divergent"
                        ? "var(--negative)"
                        : "var(--warning)",
                  fontWeight: 600,
                  letterSpacing: 1.2,
                  textTransform: "uppercase",
                  marginRight: 8,
                }}
              >
                Consensus: {consensus.consensus_grade}
              </span>
              {consensus.actionable_disagreement && (
                <span style={{ color: "var(--text-secondary)" }}>
                  {consensus.actionable_disagreement}
                </span>
              )}
            </div>
          )}
        <div style={{ display: "flex", gap: 6 }}>
          {PROVIDERS.map((p) => (
            <button
              key={p}
              type="button"
              onClick={() => setActive(p)}
              data-testid={`ai-tab-${p}`}
              style={{
                border: "1px solid var(--border-dim)",
                borderRadius: 4,
                background: active === p ? "var(--bg-panel)" : "var(--bg-base)",
                color: "var(--text-primary)",
                cursor: "pointer",
                fontFamily: "var(--font-mono)",
                fontSize: 11,
                padding: "5px 10px",
              }}
            >
              {providerLabel(p)}{" "}
              <span aria-hidden="true">
                {stateBadge(latest[p], Boolean(pendingIds[p]))}
              </span>
            </button>
          ))}
        </div>
        <ProviderTabBody
          provider={active}
          analysis={latest[active]}
          pending={Boolean(pendingIds[active])}
        />
      </div>
    </InsightPanel>
  );
}
