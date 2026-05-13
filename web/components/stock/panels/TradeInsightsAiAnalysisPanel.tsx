"use client";

import { useEffect, useRef, useState } from "react";

import { api, type TradeInsightsAiAnalysisResponse } from "@/lib/api";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;

const labelStyle = {
  fontFamily: "var(--font-mono)",
  fontSize: 9,
  color: "var(--text-muted)",
  letterSpacing: 1,
  textTransform: "uppercase" as const,
};

function MiniCard({
  label,
  value,
  note,
}: {
  label: string;
  value: string;
  note?: string | null;
}) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 10,
        minHeight: 76,
      }}
    >
      <div style={labelStyle}>{label}</div>
      <div
        style={{
          color: "var(--text-primary)",
          fontFamily: "var(--font-mono)",
          fontSize: 16,
        }}
      >
        {value}
      </div>
      {note && (
        <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
          {note}
        </div>
      )}
    </div>
  );
}

function SectionCard({
  section,
}: {
  section: Outcome["section_cards"]["market_structure"];
}) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 12,
      }}
    >
      <div style={labelStyle}>{section.title}</div>
      <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
        {section.summary}
      </div>
      {section.score != null && section.max_score != null && (
        <div
          style={{
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          score {section.score}/{section.max_score} · {section.data_quality}
        </div>
      )}
      {[
        ...(section.highlights ?? []),
        ...(section.levels ?? []).map((level) => ({
          label: level.kind,
          value: `${level.price} ${level.value}`,
          note: level.note,
        })),
      ].map((item) => (
        <div
          key={`${item.label}-${item.value}`}
          style={{ marginTop: 8, fontSize: 12 }}
        >
          <span style={{ color: "var(--text-secondary)" }}>{item.label}: </span>
          <span style={{ color: "var(--text-primary)" }}>{item.value}</span>
        </div>
      ))}
    </div>
  );
}

function OutcomeGrid({ outcome }: { outcome: Outcome }) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "minmax(220px, 1.2fr) minmax(180px, 0.8fr)",
          gap: 12,
        }}
      >
        <div>
          <div style={{ ...labelStyle, marginBottom: 4 }}>{outcome.ticker}</div>
          <div
            style={{
              color: "var(--text-primary)",
              fontSize: 18,
              fontWeight: 700,
            }}
          >
            {outcome.headline.title}
          </div>
          <div
            style={{
              color: "var(--text-secondary)",
              fontSize: 12,
              marginTop: 6,
            }}
          >
            Generated analysis from local Codex. Deterministic risk checks
            remain authoritative.
          </div>
        </div>
        <div
          style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 8 }}
        >
          <MiniCard label="Stance" value={outcome.headline.stance_label} />
          <MiniCard
            label="Score"
            value={`${outcome.headline.score}/${outcome.headline.score_scale}`}
            note={`${outcome.headline.conviction} · ${outcome.headline.conviction_label}`}
          />
        </div>
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(4, minmax(0, 1fr))",
          gap: 8,
        }}
      >
        <MiniCard
          label="Produced"
          value={outcome.analysis_produced_at.slice(0, 10)}
        />
        <MiniCard
          label="Data"
          value={outcome.snapshot.freshness_label}
          note={outcome.snapshot.data_as_of}
        />
        <MiniCard label="Risk" value={outcome.headline.primary_risk} />
        <MiniCard label="Watch" value={outcome.headline.watch_trigger} />
        {outcome.metric_cards.map((card) => (
          <MiniCard
            key={`${card.label}-${card.value}`}
            label={card.label}
            value={card.value}
            note={card.note}
          />
        ))}
      </div>

      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 8,
        }}
      >
        {outcome.scenario_cards.map((card) => (
          <MiniCard
            key={card.case}
            label={card.case}
            value={card.title}
            note={card.description}
          />
        ))}
      </div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <SectionCard section={outcome.section_cards.market_structure} />
        <SectionCard section={outcome.section_cards.volatility} />
        <SectionCard section={outcome.section_cards.flow_positioning} />
        {outcome.vrp_assessment && (
          <div
            style={{
              border: "1px solid var(--border-dim)",
              borderRadius: 4,
              padding: 12,
            }}
          >
            <div style={labelStyle}>{outcome.vrp_assessment.title}</div>
            <div style={{ color: "var(--text-primary)", fontSize: 13 }}>
              {outcome.vrp_assessment.summary}
            </div>
            <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
              {outcome.vrp_assessment.reason}
            </div>
          </div>
        )}
      </div>

      {outcome.preferred_expression && (
        <div
          style={{
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            padding: 12,
          }}
        >
          <div style={labelStyle}>Preferred Expression</div>
          <div style={{ color: "var(--text-primary)", fontSize: 15 }}>
            {outcome.preferred_expression.title}
          </div>
          <div style={{ color: "var(--text-secondary)", fontSize: 12 }}>
            {outcome.preferred_expression.why}
          </div>
          <div
            style={{
              display: "grid",
              gridTemplateColumns: "repeat(4, 1fr)",
              gap: 8,
              marginTop: 8,
            }}
          >
            <MiniCard
              label="Entry"
              value={outcome.preferred_expression.estimated_entry}
            />
            <MiniCard
              label="Max Profit"
              value={outcome.preferred_expression.max_profit_observed}
            />
            <MiniCard
              label="Max Loss"
              value={outcome.preferred_expression.max_loss_observed}
            />
            <MiniCard
              label="Status"
              value={outcome.preferred_expression.status_observed}
            />
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 12 }}>
        <List
          title="Conflicts"
          items={(outcome.conflicts ?? []).map((item) => item.description)}
        />
        <List
          title="Required Checks"
          items={(outcome.required_checks ?? []).map((item) => item.check)}
        />
        <List
          title="Rejected Ideas"
          items={(outcome.rejected_ideas ?? []).map(
            (item) => `${item.idea_id}: ${item.reason}`,
          )}
        />
        <List title="Missing Data" items={outcome.missing_data ?? []} />
      </div>
    </div>
  );
}

function List({ title, items }: { title: string; items: string[] }) {
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 12,
      }}
    >
      <div style={labelStyle}>{title}</div>
      {items.length === 0 ? (
        <div style={{ color: "var(--text-muted)", fontSize: 12 }}>None</div>
      ) : (
        items.map((item) => (
          <div
            key={item}
            style={{
              color: "var(--text-secondary)",
              fontSize: 12,
              marginTop: 4,
            }}
          >
            {item}
          </div>
        ))
      )}
    </div>
  );
}

export function TradeInsightsAiAnalysisPanel({ ticker }: { ticker: string }) {
  const [analysis, setAnalysis] =
    useState<TradeInsightsAiAnalysisResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const hydratedRef = useRef<string | null>(null);
  const requestTokenRef = useRef(0);

  useEffect(() => {
    const token = ++requestTokenRef.current;
    if (hydratedRef.current === ticker) return;
    hydratedRef.current = ticker;
    setAnalysis(null);
    setLoading(false);
    setUnavailable(false);
    let cancelled = false;
    void (async () => {
      try {
        const latest = await api.tradeInsightsAiAnalysisLatest(ticker);
        if (!cancelled && requestTokenRef.current === token && latest) {
          setAnalysis(latest);
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
      let current = started;
      let elapsedMs = 0;
      const intervalMs = 3000;
      const maxMs = 5 * 60 * 1000;
      while (current.status === "queued" || current.status === "running") {
        if (elapsedMs >= maxMs) break;
        current = await api.tradeInsightsAiAnalysisStatus(
          ticker,
          started.analysis_id,
        );
        if (!isCurrentRequest()) return;
        setAnalysis(current);
        if (current.status === "queued" || current.status === "running") {
          await new Promise((r) => setTimeout(r, intervalMs));
          if (!isCurrentRequest()) return;
          elapsedMs += intervalMs;
        }
      }
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
        {analysis?.status === "queued" || analysis?.status === "running" ? (
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
