/* @vitest-environment jsdom */
import { act, renderHook, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  useAiAnalysisPolling,
  type Provider,
} from "@/components/stock/panels/tradeInsightsAi/useAiAnalysisPolling";
import {
  api,
  type TradeInsightsAiAnalysisEnqueueResponse,
  type TradeInsightsAiAnalysisResponse,
  type TradeInsightsAiLatestPair,
} from "@/lib/api";

vi.mock("@/lib/api", async () => {
  return {
    api: {
      tradeInsightsAiAnalysis: vi.fn(),
      tradeInsightsAiAnalysisStatus: vi.fn(),
      tradeInsightsAiAnalysisLatest: vi.fn(),
    },
  };
});

const EMPTY_PAIR: TradeInsightsAiLatestPair = {
  current_prompt_version: "trade-insights-ai-v5.3",
  current_prompt_label: "v5.3",
  codex: null,
  claude: null,
  deepseek: null,
};

function baseResponse(
  overrides: Partial<TradeInsightsAiAnalysisResponse> = {},
): TradeInsightsAiAnalysisResponse {
  return {
    analysis_id: "00000000-0000-0000-0000-000000000123",
    ticker: "TSLA",
    run_id: 123,
    trade_insights_input_hash: "ti-hash",
    analysis_input_hash: "ai-hash",
    model: "deepseek-v4-pro",
    provider: "deepseek",
    prompt_version: "trade-insights-ai-v5.3",
    status: "queued",
    produced_at: null,
    outcome: null,
    markdown: null,
    error_message: null,
    requested_at: "2026-03-24T20:00:00Z",
    started_at: null,
    finished_at: null,
    reused: false,
    ...overrides,
  };
}

function enqueueResp(
  analyses: TradeInsightsAiAnalysisEnqueueResponse["analyses"],
): TradeInsightsAiAnalysisEnqueueResponse {
  return { analyses };
}

function queuedStub(provider: Provider, analysisId: string) {
  return {
    provider,
    analysis_id: analysisId,
    status: "queued" as const,
    reused: false,
    model: "deepseek-v4-pro",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((res) => {
    resolve = res;
  });
  return { promise, resolve };
}

describe("useAiAnalysisPolling", () => {
  beforeEach(() => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(EMPTY_PAIR);
  });

  it("keeps the API pair shape on the local latest/pending maps", async () => {
    // Option A: the API still returns the 3-slot pair, so the local maps keep
    // all three keys; PROVIDERS only scopes what we run and poll.
    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));
    expect(Object.keys(result.current.latestForTicker).sort()).toEqual([
      "claude",
      "codex",
      "deepseek",
    ]);
    expect(Object.keys(result.current.pendingIdsForTicker).sort()).toEqual([
      "claude",
      "codex",
      "deepseek",
    ]);
  });

  it("hydrates latest pair on mount", async () => {
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue({
      ...EMPTY_PAIR,
      deepseek: baseResponse({ status: "succeeded" }),
    });

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));

    await waitFor(() => {
      expect(result.current.latestForTicker.deepseek?.status).toBe(
        "succeeded",
      );
    });
    expect(result.current.promptMetadataForTicker.current_prompt_label).toBe(
      "v5.3",
    );
  });

  it("posts a run request and records the pending provider", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([queuedStub("deepseek", "deepseek-1")]),
    );
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValue(
      new Promise<TradeInsightsAiAnalysisResponse>(() => undefined),
    );

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));

    await act(async () => {
      await result.current.run(false);
    });

    expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledWith(
      "TSLA",
      {},
      "insights",
    );
    expect(result.current.pendingIdsForTicker.deepseek).toBe("deepseek-1");
  });

  it("does not re-POST while the provider is still pending", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([queuedStub("deepseek", "deepseek-hung")]),
    );
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValue(
      new Promise<TradeInsightsAiAnalysisResponse>(() => undefined),
    );

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));

    await act(async () => {
      await result.current.run(false);
    });
    await waitFor(() => {
      expect(result.current.pendingIdsForTicker.deepseek).toBe(
        "deepseek-hung",
      );
    });

    await act(async () => {
      await result.current.run(false);
    });

    // deepseek is still pending → the rerun is filtered out before the POST.
    expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledTimes(1);
  });

  it("keeps polling the pending provider until it resolves", async () => {
    const deepseekStatus = deferred<TradeInsightsAiAnalysisResponse>();
    const deepseekSucceeded = baseResponse({
      analysis_id: "deepseek-hung",
      status: "succeeded",
    });

    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([queuedStub("deepseek", "deepseek-hung")]),
    );
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValueOnce(
      deepseekStatus.promise,
    );
    vi.mocked(api.tradeInsightsAiAnalysisLatest)
      .mockResolvedValueOnce(EMPTY_PAIR)
      .mockResolvedValueOnce(EMPTY_PAIR)
      .mockResolvedValueOnce({ ...EMPTY_PAIR, deepseek: deepseekSucceeded });

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));

    await act(async () => {
      await result.current.run(false);
    });
    await waitFor(() => {
      expect(result.current.pendingIdsForTicker.deepseek).toBe(
        "deepseek-hung",
      );
    });

    await act(async () => {
      deepseekStatus.resolve(deepseekSucceeded);
      await deepseekStatus.promise;
    });

    await waitFor(() => {
      expect(result.current.latestForTicker.deepseek?.status).toBe(
        "succeeded",
      );
      expect(result.current.pendingIdsForTicker.deepseek).toBeNull();
    });
  });

  it("marks analysis unavailable when run request returns 503", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockRejectedValueOnce(
      new Error("API 503 for /ai-analysis: disabled"),
    );

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));

    await act(async () => {
      await result.current.run(false);
    });

    expect(result.current.unavailableForTicker).toBe(true);
    expect(result.current.canRun).toBe(false);
  });
});
