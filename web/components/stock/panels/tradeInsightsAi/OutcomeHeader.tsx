import type { TradeInsightsAiAnalysisResponse } from "@/lib/api";
import {
  CompactNote,
  ProviderKeyValueGrid,
  type Tone,
  labelStyle,
  plainText,
  shortDate,
  toneColor,
} from "./ui";
import type { Provider } from "./useAiAnalysisPolling";

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;

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

export function OutcomeHeader({
  outcome,
  provider,
  providerLabel,
}: {
  outcome: Outcome;
  provider: Provider;
  providerLabel: (provider: Provider) => string;
}) {
  const topMetrics = outcome.metric_cards.slice(0, 6).map((card) => ({
    label: card.label,
    value: card.value,
  }));
  const directionalBias = outcome.headline.directional_bias as DirectionalBias;
  const entryState = outcome.headline.entry_state as EntryState;
  const tradeIntent = outcome.headline.trade_intent as TradeIntent;
  const biasFrameColor = toneColor(DIRECTIONAL_BIAS_TONE[directionalBias]);

  return (
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
      <ProviderKeyValueGrid
        items={[
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
        <CompactNote label="Primary Risk" value={outcome.headline.primary_risk} />
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
  );
}
