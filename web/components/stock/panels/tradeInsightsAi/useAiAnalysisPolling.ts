"use client";

import { useCallback, useEffect, useRef, useState } from "react";

import {
  api,
  type TradeInsightsAiAnalysisResponse,
  type TradeInsightsAiLatestPair,
} from "@/lib/api";

export const AI_ANALYSIS_POLL_MAX_MS = 10 * 60 * 1000;

export type Provider = "codex" | "claude" | "deepseek";
export const PROVIDERS: readonly Provider[] = [
  "codex",
  "claude",
  "deepseek",
] as const;

export type ProviderAnalysisPair = {
  codex: TradeInsightsAiAnalysisResponse | null;
  claude: TradeInsightsAiAnalysisResponse | null;
  deepseek: TradeInsightsAiAnalysisResponse | null;
};

export type ProviderPendingPair = {
  codex: string | null;
  claude: string | null;
  deepseek: string | null;
};

export type ProviderConsensus = NonNullable<
  TradeInsightsAiLatestPair["provider_consensus"]
>;

export type PromptMetadata = Pick<
  TradeInsightsAiLatestPair,
  "current_prompt_label" | "current_prompt_version"
>;

export const EMPTY_LATEST: ProviderAnalysisPair = {
  codex: null,
  claude: null,
  deepseek: null,
};
export const EMPTY_PENDING: ProviderPendingPair = {
  codex: null,
  claude: null,
  deepseek: null,
};
export const EMPTY_PROMPT_METADATA: PromptMetadata = {
  current_prompt_label: null,
  current_prompt_version: "",
};

export function isInFlight(analysis: TradeInsightsAiAnalysisResponse): boolean {
  return analysis.status === "queued" || analysis.status === "running";
}

function promptMetadataFromPair(
  pair: TradeInsightsAiLatestPair,
): PromptMetadata {
  return {
    current_prompt_label: pair.current_prompt_label ?? null,
    current_prompt_version: pair.current_prompt_version,
  };
}

// Single source of truth for projecting the API /latest pair onto our local
// per-provider shape. Keeping this provider-count-agnostic means adding a
// fourth provider later is a one-line change to PROVIDERS + the two pair types.
function latestFromPair(pair: TradeInsightsAiLatestPair): ProviderAnalysisPair {
  return {
    codex: pair.codex ?? null,
    claude: pair.claude ?? null,
    deepseek: pair.deepseek ?? null,
  };
}

export type AnalysisKind = "insights" | "blast";

export function useAiAnalysisPolling(
  ticker: string,
  kind: AnalysisKind = "insights",
) {
  const [latest, setLatest] = useState<ProviderAnalysisPair>(EMPTY_LATEST);
  const [consensus, setConsensus] = useState<ProviderConsensus | null>(null);
  const [promptMetadata, setPromptMetadata] = useState<PromptMetadata>(
    EMPTY_PROMPT_METADATA,
  );
  const [pendingIds, setPendingIds] =
    useState<ProviderPendingPair>(EMPTY_PENDING);
  const [loadedTicker, setLoadedTicker] = useState(ticker);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const requestTokenRef = useRef(0);
  const pollTokenRef = useRef<ProviderPendingPair>(EMPTY_PENDING);

  const pollOne = useCallback(
    async (provider: Provider, analysisId: string) => {
      const isCurrentPoll = () => pollTokenRef.current[provider] === analysisId;
      let current: TradeInsightsAiAnalysisResponse;
      try {
        current = await api.tradeInsightsAiAnalysisStatus(ticker, analysisId);
      } catch (err) {
        if (!isCurrentPoll()) return;
        if (String(err).includes("503")) {
          setUnavailable(true);
        }
        return;
      }
      if (!isCurrentPoll()) return;
      let elapsedMs = 0;
      const intervalMs = 3000;
      const maxMs = AI_ANALYSIS_POLL_MAX_MS;
      while (isInFlight(current)) {
        if (elapsedMs >= maxMs) break;
        await new Promise((r) => setTimeout(r, intervalMs));
        if (!isCurrentPoll()) return;
        elapsedMs += intervalMs;
        try {
          current = await api.tradeInsightsAiAnalysisStatus(ticker, analysisId);
        } catch (err) {
          if (!isCurrentPoll()) return;
          if (String(err).includes("503")) {
            setUnavailable(true);
          }
          return;
        }
        if (!isCurrentPoll()) return;
      }
      try {
        const pair = await api.tradeInsightsAiAnalysisLatest(ticker, kind);
        if (!isCurrentPoll()) return;
        setLatest(latestFromPair(pair));
        setConsensus(pair.provider_consensus ?? null);
        setPromptMetadata(promptMetadataFromPair(pair));
      } catch {
        if (isCurrentPoll()) {
          setLatest((prev) => ({ ...prev, [provider]: current }));
        }
      }
      if (isCurrentPoll()) {
        pollTokenRef.current = { ...pollTokenRef.current, [provider]: null };
        setPendingIds((prev) => ({ ...prev, [provider]: null }));
      }
    },
    [ticker, kind],
  );

  useEffect(() => {
    const token = ++requestTokenRef.current;
    let cancelled = false;
    void (async () => {
      try {
        const pair = await api.tradeInsightsAiAnalysisLatest(ticker, kind);
        if (!cancelled && requestTokenRef.current === token) {
          setLoadedTicker(ticker);
          setLatest(latestFromPair(pair));
          setConsensus(pair.provider_consensus ?? null);
          setPromptMetadata(promptMetadataFromPair(pair));
          pollTokenRef.current = EMPTY_PENDING;
          setPendingIds(EMPTY_PENDING);
          setLoading(false);
          setUnavailable(false);
        }
      } catch (err) {
        if (!cancelled && requestTokenRef.current === token) {
          setLoadedTicker(ticker);
          setLatest(EMPTY_LATEST);
          setConsensus(null);
          setPromptMetadata(EMPTY_PROMPT_METADATA);
          pollTokenRef.current = EMPTY_PENDING;
          setPendingIds(EMPTY_PENDING);
          setLoading(false);
          if (String(err).includes("503")) {
            setUnavailable(true);
          }
        }
      }
    })();
    return () => {
      cancelled = true;
      requestTokenRef.current += 1;
      pollTokenRef.current = EMPTY_PENDING;
    };
  }, [ticker, kind]);

  const isLoadedTicker = loadedTicker === ticker;
  const latestForTicker = isLoadedTicker ? latest : EMPTY_LATEST;
  const consensusForTicker = isLoadedTicker ? consensus : null;
  const promptMetadataForTicker = isLoadedTicker
    ? promptMetadata
    : EMPTY_PROMPT_METADATA;
  const pendingIdsForTicker = isLoadedTicker ? pendingIds : EMPTY_PENDING;
  const loadingForTicker = isLoadedTicker ? loading : false;
  const unavailableForTicker = isLoadedTicker ? unavailable : false;

  async function run(force_rerun = false) {
    const token = ++requestTokenRef.current;
    const isCurrentRequest = () => requestTokenRef.current === token;
    setLoadedTicker(ticker);
    setLoading(true);
    setUnavailable(false);
    const providersToRun: Provider[] = PROVIDERS.filter(
      (p) => !pendingIdsForTicker[p],
    );
    if (providersToRun.length === 0) {
      setLoading(false);
      return;
    }
    try {
      const body: { force_rerun?: boolean; providers?: Provider[] } = {};
      if (force_rerun) body.force_rerun = true;
      if (providersToRun.length < PROVIDERS.length) {
        body.providers = providersToRun;
      }
      const resp = await api.tradeInsightsAiAnalysis(ticker, body, kind);
      if (!isCurrentRequest()) return;
      const newPending: ProviderPendingPair = { ...pendingIdsForTicker };
      for (const stub of resp.analyses) {
        if (stub.status === "succeeded" && stub.reused) {
          newPending[stub.provider as Provider] = null;
          continue;
        }
        newPending[stub.provider as Provider] = stub.analysis_id;
      }
      setPendingIds(newPending);
      try {
        const pair = await api.tradeInsightsAiAnalysisLatest(ticker, kind);
        if (isCurrentRequest()) {
          setLatest(latestFromPair(pair));
          setConsensus(pair.provider_consensus ?? null);
          setPromptMetadata(promptMetadataFromPair(pair));
        }
      } catch {
        /* tolerate */
      }
      if (isCurrentRequest()) setLoading(false);
      for (const p of PROVIDERS) {
        const id = newPending[p];
        if (id) {
          pollTokenRef.current = { ...pollTokenRef.current, [p]: id };
          void pollOne(p, id);
        }
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

  const allPending = PROVIDERS.every((p) => Boolean(pendingIdsForTicker[p]));
  const anyFailed = PROVIDERS.some(
    (p) => latestForTicker[p]?.status === "failed",
  );
  const anySucceeded = PROVIDERS.some(
    (p) => latestForTicker[p]?.status === "succeeded",
  );
  const canRun = !unavailableForTicker && !allPending;
  const forceRun = anySucceeded || anyFailed;
  const actionLabel =
    loadingForTicker || allPending ? "Running…" : "Run Analysis";

  return {
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
  };
}
