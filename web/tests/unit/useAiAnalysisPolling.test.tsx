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
    model: "codex-default",
    provider: "codex",
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
    model: provider === "codex" ? "codex-default" : "claude-opus-4-7",
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

  it("hydrates latest pair on mount", async () => {
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue({
      ...EMPTY_PAIR,
      codex: baseResponse({ status: "succeeded" }),
    });

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));

    await waitFor(() => {
      expect(result.current.latestForTicker.codex?.status).toBe("succeeded");
    });
    expect(result.current.promptMetadataForTicker.current_prompt_label).toBe(
      "v5.3",
    );
  });

  it("posts a run request and records pending providers", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([queuedStub("codex", "codex-1"), queuedStub("claude", "claude-1")]),
    );
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValue(
      new Promise<TradeInsightsAiAnalysisResponse>(() => undefined),
    );

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));

    await act(async () => {
      await result.current.run(false);
    });

    expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledWith("TSLA", {});
    expect(result.current.pendingIdsForTicker.codex).toBe("codex-1");
    expect(result.current.pendingIdsForTicker.claude).toBe("claude-1");
  });

  it("reruns only the provider that is not already pending", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([
        queuedStub("codex", "codex-hung"),
        {
          provider: "claude",
          analysis_id: "claude-cached",
          status: "succeeded",
          reused: true,
          model: "claude-opus-4-7",
        },
      ]),
    );
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([queuedStub("claude", "claude-rerun")]),
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
      expect(result.current.pendingIdsForTicker.codex).toBe("codex-hung");
    });

    await act(async () => {
      await result.current.run(false);
    });

    expect(api.tradeInsightsAiAnalysis).toHaveBeenLastCalledWith("TSLA", {
      providers: ["claude"],
    });
  });

  it("keeps polling an existing provider when a partial rerun fails", async () => {
    const codexStatus = deferred<TradeInsightsAiAnalysisResponse>();
    const codexSucceeded = baseResponse({
      analysis_id: "codex-hung",
      status: "succeeded",
    });

    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp([
        queuedStub("codex", "codex-hung"),
        {
          provider: "claude",
          analysis_id: "claude-cached",
          status: "succeeded",
          reused: true,
          model: "claude-opus-4-7",
        },
      ]),
    );
    vi.mocked(api.tradeInsightsAiAnalysis).mockRejectedValueOnce(
      new Error("API 503 for /ai-analysis: disabled"),
    );
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValueOnce(
      codexStatus.promise,
    );
    vi.mocked(api.tradeInsightsAiAnalysisLatest)
      .mockResolvedValueOnce(EMPTY_PAIR)
      .mockResolvedValueOnce(EMPTY_PAIR)
      .mockResolvedValueOnce({ ...EMPTY_PAIR, codex: codexSucceeded });

    const { result } = renderHook(() => useAiAnalysisPolling("TSLA"));
    await waitFor(() => expect(result.current.canRun).toBe(true));

    await act(async () => {
      await result.current.run(false);
    });
    await waitFor(() => {
      expect(result.current.pendingIdsForTicker.codex).toBe("codex-hung");
    });

    await act(async () => {
      await result.current.run(false);
    });
    expect(api.tradeInsightsAiAnalysis).toHaveBeenLastCalledWith("TSLA", {
      providers: ["claude"],
    });

    await act(async () => {
      codexStatus.resolve(codexSucceeded);
      await codexStatus.promise;
    });

    await waitFor(() => {
      expect(result.current.latestForTicker.codex?.status).toBe("succeeded");
      expect(result.current.pendingIdsForTicker.codex).toBeNull();
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
