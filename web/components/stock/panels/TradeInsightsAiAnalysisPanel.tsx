"use client";

import { useEffect, useRef, useState } from "react";
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
    <div style={{ color: "var(--text-primary)", fontSize: 12, fontWeight: 700 }}>
      {children}
    </div>
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
      <div style={{ color: "var(--text-secondary)", fontSize: 12, lineHeight: 1.4 }}>
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
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        borderLeft: `6px solid ${toneColor(tone)}`,
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
          style={{
            color: "var(--text-primary)",
            fontSize: 15,
            fontWeight: 700,
            lineHeight: 1.25,
          }}
        >
          {title}
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
        <div key={item} style={{ color: "var(--text-secondary)", fontSize: 12 }}>
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
      (item) => `${item.label}: ${tidy(item.value)}${item.note ? ` · ${item.note}` : ""}`,
    ),
    ...(section.levels ?? []).map(
      (level) =>
        `${level.kind}: ${tidy(level.price)} ${tidy(level.value)}${
          level.note ? ` · ${level.note}` : ""
        }`,
    ),
  ];
  return (
    <AnalysisCard title={section.title} subtitle={scoreText(section)} tone={tone}>
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

function OutcomeGrid({ outcome }: { outcome: Outcome }) {
  const preferred = outcome.preferred_expression;
  const topMetrics = outcome.metric_cards.slice(0, 6).map((card) => ({
    label: card.label,
    value: card.value,
  }));
  const requiredChecks = (outcome.required_checks ?? []).map((item) => item.check);
  const conflicts = (outcome.conflicts ?? []).map((item) => item.description);
  const missing = outcome.missing_data ?? [];

  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div
        style={{
          border: "1px solid var(--border-dim)",
          borderLeft: `6px solid ${toneColor(toneFromText(outcome.headline.stance_label))}`,
          borderRadius: 4,
          padding: "12px 14px",
          background: "var(--bg-panel)",
        }}
      >
        <div style={labelStyle}>{outcome.ticker} AI Analysis</div>
        <div
          style={{
            color: "var(--text-primary)",
            fontSize: 16,
            fontWeight: 700,
            lineHeight: 1.25,
            marginTop: 4,
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
          {plainText(outcome.dominant_read?.summary ?? outcome.headline.top_reason)}
        </div>
        <KeyValueGrid
          items={[
            { label: "Stance", value: outcome.headline.stance_label },
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
            gridTemplateColumns: "repeat(2, minmax(0, 1fr))",
            gap: 8,
            marginTop: 10,
          }}
        >
          <CompactNote label="Primary Risk" value={outcome.headline.primary_risk} />
          <CompactNote label="Trigger To Watch" value={outcome.headline.watch_trigger} />
        </div>
        <div
          style={{
            color: "var(--text-muted)",
            fontSize: 12,
            fontWeight: 700,
            marginTop: 10,
          }}
        >
          Generated analysis from local Codex · {outcome.analysis_produced_at.slice(0, 10)} · Not financial advice
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
            gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
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
            gridTemplateColumns: "minmax(0, 0.95fr) minmax(0, 0.9fr) minmax(0, 1.15fr)",
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
              <KeyValueGrid
                items={outcome.vrp_assessment.metrics.slice(0, 6).map((metric) => ({
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
                    { label: "Max Profit", value: preferred.max_profit_observed },
                    { label: "Max Loss", value: preferred.max_loss_observed },
                    { label: "R:R", value: preferred.reward_risk },
                    { label: "Status", value: preferred.status_observed },
                  ]}
                />
                <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
                  {plainText(preferred.why)}
                </div>
                <BulletList items={preferred.management_notes ?? []} limit={3} />
              </>
            ) : (
              <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
                No entry candidate is ready yet. The generated structures stay
                pending validation until the checklist passes.
              </div>
            )}
          </AnalysisCard>
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

export function TradeInsightsAiAnalysisPanel({ ticker }: { ticker: string }) {
  const [analysis, setAnalysis] =
    useState<TradeInsightsAiAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const requestTokenRef = useRef(0);

  async function pollAnalysis(
    started: TradeInsightsAiAnalysisResponse,
    token: number,
  ) {
    const isCurrentRequest = () => requestTokenRef.current === token;
    let current = started;
    let elapsedMs = 0;
    const intervalMs = 3000;
    const maxMs = AI_ANALYSIS_POLL_MAX_MS;
    while (isInFlight(current)) {
      if (elapsedMs >= maxMs) break;
      current = await api.tradeInsightsAiAnalysisStatus(
        ticker,
        started.analysis_id,
      );
      if (!isCurrentRequest()) return;
      setAnalysis(current);
      if (isInFlight(current)) {
        await new Promise((r) => setTimeout(r, intervalMs));
        if (!isCurrentRequest()) return;
        elapsedMs += intervalMs;
      }
    }
  }

  useEffect(() => {
    const token = ++requestTokenRef.current;
    setAnalysis(null);
    setLoading(false);
    setUnavailable(false);
    let cancelled = false;
    void (async () => {
      try {
        const latest = await api.tradeInsightsAiAnalysisLatest(ticker);
        if (!cancelled && requestTokenRef.current === token && latest) {
          setAnalysis(latest);
          if (isInFlight(latest)) {
            setLoading(true);
            try {
              await pollAnalysis(latest, token);
            } catch (err) {
              if (!cancelled && requestTokenRef.current === token) {
                if (String(err).includes("503")) {
                  setUnavailable(true);
                } else {
                  setAnalysis((currentAnalysis) => ({
                    ...currentAnalysis,
                    status: "failed",
                    error_message: String(err),
                  }) as TradeInsightsAiAnalysisResponse);
                }
              }
            } finally {
              if (!cancelled && requestTokenRef.current === token) {
                setLoading(false);
              }
            }
          }
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
    try {
      const started = await api.tradeInsightsAiAnalysis(
        ticker,
        force_rerun ? { force_rerun } : {},
      );
      if (!isCurrentRequest()) return;
      setAnalysis(started);
      await pollAnalysis(started, token);
    } catch (err) {
      if (!isCurrentRequest()) return;
      if (String(err).includes("503")) {
        setUnavailable(true);
      } else {
        setAnalysis((currentAnalysis) => ({
          ...currentAnalysis,
          status: "failed",
          error_message: String(err),
        }) as TradeInsightsAiAnalysisResponse);
      }
    } finally {
      if (isCurrentRequest()) {
        setLoading(false);
      }
    }
  }

  const failed = analysis?.status === "failed";
  return (
    <InsightPanel
      heading="AI ANALYSIS"
      subheading="Generated commentary from local Codex"
    >
      <div style={{ display: "grid", gap: 12 }}>
        {unavailable && (
          <InsightStatusBanner
            text="Local Codex AI analysis is not enabled for this environment."
            severity="info"
          />
        )}
        {!analysis && !unavailable && (
          <button type="button" onClick={() => run()} disabled={loading}>
            {loading ? "Running..." : "Run AI Analysis"}
          </button>
        )}
        {analysis && isInFlight(analysis) ? (
          <InsightStatusBanner
            text={`AI analysis ${analysis.status}`}
            severity="info"
          />
        ) : null}
        {failed && (
          <>
            <InsightStatusBanner
              text={analysis.error_message ?? "AI analysis failed"}
              severity="negative"
            />
            <button type="button" onClick={() => run(true)} disabled={loading}>
              Retry
            </button>
          </>
        )}
        {analysis?.status === "succeeded" && analysis.outcome && (
          <OutcomeGrid outcome={analysis.outcome} />
        )}
      </div>
    </InsightPanel>
  );
}
