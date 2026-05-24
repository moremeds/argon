/* @vitest-environment jsdom */
import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AI_ANALYSIS_POLL_MAX_MS,
  TradeInsightsAiAnalysisPanel,
} from "@/components/stock/panels/TradeInsightsAiAnalysisPanel";
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

const EMPTY_PAIR: TradeInsightsAiLatestPair = { codex: null, claude: null };

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
    prompt_version: "trade-insights-ai-v4",
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

type Outcome = NonNullable<TradeInsightsAiAnalysisResponse["outcome"]>;
type SectionCard = Outcome["section_cards"]["market_structure"];

function neutralSection(title: string): SectionCard {
  return {
    title,
    summary: "neutral",
    score: 4,
    max_score: 8,
    highlights: [],
    levels: [],
    tone: "neutral",
    data_quality: "ok",
  } as SectionCard;
}

function succeededResponse(
  overrides: Partial<TradeInsightsAiAnalysisResponse> = {},
): TradeInsightsAiAnalysisResponse {
  const outcome: Outcome = {
    schema_version: "trade-insights-ai-v4",
    analysis_produced_at: "2026-03-24T20:18:42Z",
    ticker: "TSLA",
    underlying_price: "$380.88",
    snapshot: {
      run_id: 123,
      trade_insights_input_hash: "ti-hash",
      analysis_input_hash: "ai-hash",
      data_as_of: "2026-03-24",
      freshness_label: "mixed",
      source_notes: ["Flow: same-day snapshot"],
    },
    headline: {
      title: "TSLA near gamma resistance with cheap vol and bullish flow",
      stance: "bullish",
      stance_label: "BUY setup",
      score: 31,
      score_scale: 100,
      conviction: "B",
      conviction_label: "Moderate",
      top_reason: "Cheap IV plus bullish flow",
      primary_risk: "$382.50 GEX wall may cap immediate upside",
      watch_trigger: "Break above $382.50 with volume",
    },
    metric_cards: [],
    scenario_cards: [],
    score_breakdown: [],
    section_cards: {
      market_structure: neutralSection("Market Structure"),
      volatility: neutralSection("Volatility"),
      flow_positioning: neutralSection("Flow"),
    },
    dominant_read: {
      headline: "Neutral",
      summary: "Neutral overall.",
      confidence_commentary: "Moderate",
      data_quality_commentary: "Mixed",
    },
    vrp_assessment: {
      signal: "thin",
      title: "VRP",
      summary: "neutral",
      reason: "thin",
    },
    rendering: { disclaimer: "for educational use only" },
    guardrails: {
      statuses_preserved: true,
      risk_flags_preserved: true,
      no_executable_recommendations: true,
    },
  } as Outcome;
  return {
    ...baseResponse(),
    status: "succeeded",
    produced_at: "2026-03-24T20:18:42Z",
    finished_at: "2026-03-24T20:19:00Z",
    outcome,
    markdown: "unused",
    ...overrides,
  };
}

function enqueueResp(
  codexStubStatus: "queued" | "succeeded" = "queued",
  claudeStubStatus: "queued" | "succeeded" | null = "queued",
): TradeInsightsAiAnalysisEnqueueResponse {
  const analyses: TradeInsightsAiAnalysisEnqueueResponse["analyses"] = [
    {
      provider: "codex",
      analysis_id: "11111111-1111-1111-1111-111111111111",
      status: codexStubStatus,
      reused: codexStubStatus === "succeeded",
      model: "codex-default",
    },
  ];
  if (claudeStubStatus) {
    analyses.push({
      provider: "claude",
      analysis_id: "22222222-2222-2222-2222-222222222222",
      status: claudeStubStatus,
      reused: claudeStubStatus === "succeeded",
      model: "claude-opus-4-7",
    });
  }
  return { analyses };
}

describe("TradeInsightsAiAnalysisPanel", () => {
  beforeEach(() => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(EMPTY_PAIR);
  });

  it("renders Codex and Claude tabs with empty state by default", async () => {
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    expect(await screen.findByTestId("ai-tab-codex")).toBeDefined();
    expect(screen.getByTestId("ai-tab-claude")).toBeDefined();
    expect(screen.getByText("AI ANALYSIS")).toBeDefined();
    expect(screen.getByText("Run Analysis")).toBeDefined();
  });

  it("keeps polling long enough for the deeper local Codex prompt", () => {
    expect(AI_ANALYSIS_POLL_MAX_MS).toBe(10 * 60 * 1000);
  });

  it("hydrates latest pair from /latest on mount", async () => {
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue({
      codex: succeededResponse(),
      claude: succeededResponse({
        analysis_id: "33333333-3333-3333-3333-333333333333",
        provider: "claude",
        model: "claude-opus-4-7",
      }),
    });
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    expect(
      await screen.findByText(
        "TSLA near gamma resistance with cheap vol and bullish flow",
      ),
    ).toBeDefined();
  });

  it("clicking Run fires POST and polls until succeeded", async () => {
    // First /latest call (on mount) returns empty; second (post-run refresh)
    // returns the succeeded pair.
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValueOnce(
      EMPTY_PAIR,
    );
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue({
      codex: succeededResponse(),
      claude: succeededResponse({
        analysis_id: "33333333-3333-3333-3333-333333333333",
        provider: "claude",
        model: "claude-opus-4-7",
      }),
    });
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp("queued", "queued"),
    );
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockResolvedValue(
      succeededResponse(),
    );
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    fireEvent.click(await screen.findByText("Run Analysis"));
    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledWith("TSLA", {}),
    );
    expect(await screen.findByText("BUY setup")).toBeDefined();
  });

  it("shows unavailable banner when POST returns 503", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockRejectedValueOnce(
      new Error("API 503 for /ai-analysis: disabled"),
    );
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    fireEvent.click(await screen.findByText("Run Analysis"));
    expect(await screen.findByText(/not enabled/i)).toBeDefined();
  });

  it("skips polling when both providers cache-hit on Run", async () => {
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(EMPTY_PAIR);
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(
      enqueueResp("succeeded", "succeeded"),
    );
    // /latest is also refreshed after the run resolves with the cached pair.
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue({
      codex: succeededResponse(),
      claude: succeededResponse({
        analysis_id: "33333333-3333-3333-3333-333333333333",
        provider: "claude",
        model: "claude-opus-4-7",
      }),
    });
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    fireEvent.click(await screen.findByText("Run Analysis"));
    await waitFor(() => expect(api.tradeInsightsAiAnalysis).toHaveBeenCalled());
    // No polling expected when both stubs are succeeded+reused.
    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysisStatus).not.toHaveBeenCalled(),
    );
  });

  it("Run-while-codex-pending only POSTs claude (provider isolation)", async () => {
    // After the first Run we leave codex with a queued (hung) row and claude
    // with a cache-hit reused-succeeded. The panel maps that to
    // pendingIds = { codex: "<id>", claude: null } via the new
    // 'reused+succeeded → clear pending' branch.
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(EMPTY_PAIR);
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce({
      analyses: [
        {
          provider: "codex",
          analysis_id: "codex-hung-1",
          status: "queued",
          reused: false,
          model: "codex-default",
        },
        {
          provider: "claude",
          analysis_id: "claude-cached-1",
          status: "succeeded",
          reused: true,
          model: "claude-opus-4-7",
        },
      ],
    });
    // Codex pollOne stays at status=queued forever (simulating a hung worker).
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockResolvedValue(
      baseResponse({ analysis_id: "codex-hung-1", status: "queued" }),
    );

    // Second Run will arrive here — assert the body has providers=["claude"].
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce({
      analyses: [
        {
          provider: "claude",
          analysis_id: "claude-rerun-2",
          status: "queued",
          reused: false,
          model: "claude-opus-4-7",
        },
      ],
    });

    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);

    // First click: triggers the initial Run that sets the hung-codex state.
    fireEvent.click(await screen.findByText("Run Analysis"));
    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledTimes(1),
    );

    // Second click: button must be re-enabled because allPending=false
    // (claude was cleared on cache hit, codex still pending but that alone
    // does not block Run). POST scope must be just claude.
    fireEvent.click(await screen.findByText("Run Analysis"));
    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledTimes(2),
    );
    const lastCall = vi.mocked(api.tradeInsightsAiAnalysis).mock.calls.at(-1);
    expect(lastCall?.[0]).toBe("TSLA");
    expect(lastCall?.[1]?.providers).toEqual(["claude"]);
  });

  it("switching to Claude tab renders the Claude analysis body", async () => {
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue({
      codex: null,
      claude: succeededResponse({
        analysis_id: "33333333-3333-3333-3333-333333333333",
        provider: "claude",
        model: "claude-opus-4-7",
      }),
    });
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    // Initially codex tab is active and shows "No analysis yet".
    expect(await screen.findByText(/No analysis yet for Codex/i)).toBeDefined();
    fireEvent.click(screen.getByTestId("ai-tab-claude"));
    expect(await screen.findByText("BUY setup")).toBeDefined();
  });
});
