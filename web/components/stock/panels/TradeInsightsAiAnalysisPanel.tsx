"use client";

import { useState } from "react";

import { InsightPanel, InsightStatusBanner } from "./InsightPanel";
import {
  type Provider,
  PROVIDERS,
  useAiAnalysisPolling,
} from "./tradeInsightsAi/useAiAnalysisPolling";
import { ProviderTabBody } from "./tradeInsightsAi/ProviderTabBody";
import { ProviderTabBar } from "./tradeInsightsAi/ProviderTabBar";

export { AI_ANALYSIS_POLL_MAX_MS } from "./tradeInsightsAi/useAiAnalysisPolling";

export function TradeInsightsAiAnalysisPanel({ ticker }: { ticker: string }) {
  const [active, setActive] = useState<Provider>("deepseek");
  const {
    latestForTicker,
    loadingForTicker,
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
        <ProviderTabBar
          active={active}
          latest={latestForTicker}
          loading={loadingForTicker}
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
