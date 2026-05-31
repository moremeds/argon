"use client";

import { useState } from "react";

import { InsightPanel, InsightStatusBanner } from "./InsightPanel";
import {
  type Provider,
  PROVIDERS,
  useAiAnalysisPolling,
} from "./tradeInsightsAi/useAiAnalysisPolling";
import { ConsensusBreakdown } from "./tradeInsightsAi/ConsensusBreakdown";
import { ProviderTabBody } from "./tradeInsightsAi/ProviderTabBody";
import { ProviderTabBar } from "./tradeInsightsAi/ProviderTabBar";

export { AI_ANALYSIS_POLL_MAX_MS } from "./tradeInsightsAi/useAiAnalysisPolling";

export function TradeInsightsAiAnalysisPanel({ ticker }: { ticker: string }) {
  const [active, setActive] = useState<Provider>("codex");
  const {
    consensusForTicker,
    latestForTicker,
    pendingIdsForTicker,
    promptMetadataForTicker,
    runOne,
    unavailableForTicker,
  } = useAiAnalysisPolling(ticker);
  return (
    <InsightPanel heading="AI ANALYSIS">
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
          onRun={(p) => runOne(p, true)}
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
