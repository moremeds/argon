/* @vitest-environment jsdom */
import { StrictMode } from "react";
import { act, fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import {
  AI_ANALYSIS_POLL_MAX_MS,
  TradeInsightsAiAnalysisPanel,
} from "@/components/stock/panels/TradeInsightsAiAnalysisPanel";
import { api, type TradeInsightsAiAnalysisResponse } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  return {
    api: {
      tradeInsightsAiAnalysis: vi.fn(),
      tradeInsightsAiAnalysisStatus: vi.fn(),
      tradeInsightsAiAnalysisLatest: vi.fn(),
    },
  };
});

const baseResponse: TradeInsightsAiAnalysisResponse = {
  analysis_id: "00000000-0000-0000-0000-000000000123",
  ticker: "TSLA",
  run_id: 123,
  trade_insights_input_hash: "ti-hash",
  analysis_input_hash: "ai-hash",
  model: "codex-default",
  prompt_version: "trade-insights-ai-v1",
  status: "queued",
  produced_at: null,
  outcome: null,
  markdown: null,
  error_message: null,
  requested_at: "2026-03-24T20:00:00Z",
  started_at: null,
  finished_at: null,
  reused: false,
};

function succeededResponse(): TradeInsightsAiAnalysisResponse {
  return {
    ...baseResponse,
    status: "succeeded",
    produced_at: "2026-03-24T20:18:42Z",
    outcome: {
      schema_version: "trade-insights-ai-v1",
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
      metric_cards: [
        {
          label: "IV Rank",
          value: "3.4/100",
          tone: "bullish",
          source_path: "tabs.volatility.header.iv_rank",
          note: "Options screen historically cheap.",
        },
        {
          label: "Net Premium",
          value: "+$524.3M",
          tone: "bullish",
          source_path: "tabs.flow.flow.net_premium",
          note: "One-day snapshot.",
        },
      ],
      scenario_cards: [
        {
          case: "upside",
          tone: "bullish",
          title: "Break $382.50 wall",
          description: "$392-$400 target zone.",
        },
      ],
      score_breakdown: [
        {
          section: "market_structure",
          score: 8,
          max_score: 28,
          summary: "Positive gamma with nearby resistance.",
        },
      ],
      section_cards: {
        market_structure: {
          title: "Market Structure",
          score: 8,
          max_score: 28,
          summary: "Positive gamma above the flip.",
          highlights: [],
          levels: [],
          data_quality: "high",
        },
        volatility: {
          title: "Volatility",
          score: 8,
          max_score: 28,
          summary: "IV is cheap versus its own range.",
          highlights: [],
          levels: [],
          data_quality: "medium",
        },
        flow_positioning: {
          title: "Flow & Positioning",
          score: 15,
          max_score: 44,
          summary: "Bullish net premium supports breakout monitoring.",
          highlights: [],
          levels: [],
          data_quality: "medium",
        },
      },
      vrp_assessment: {
        signal: "do_not_sell",
        title: "VRP Assessment",
        summary: "IV rank is near the 52-week floor.",
        metrics: [{ label: "VRP", value: "7.6%", tone: "neutral", note: "" }],
        reason: "Failed VRP entry threshold.",
      },
      preferred_expression: {
        idea_id: "A",
        structure: "bull_call_spread",
        title: "Bull Call Spread - TSLA",
        subtitle: "Buy $385 Call / Sell $400 Call",
        estimated_entry: "~$6.40 debit",
        max_profit_observed: "~$8.60",
        max_loss_observed: "~$6.40",
        reward_risk: "1.34:1",
        why: "Cleanest defined-risk expression.",
        management_notes: ["Verify before sizing."],
        status_observed: "needs_check",
        risk_flags_observed: ["verify_bid_ask"],
      },
      dominant_read: {
        headline: "Cheap vol with bullish flow near resistance.",
        summary: "Plain-English synthesis.",
        confidence_commentary: "Moderate confidence.",
        data_quality_commentary: "Mixed freshness.",
      },
      best_expressions: [],
      conflicts: [
        {
          lens: "flow_vs_structure",
          severity: "medium",
          description: "Bullish flow conflicts with nearby resistance.",
          affected_idea_ids: ["A"],
        },
      ],
      required_checks: [
        {
          check: "Confirm event calendar",
          reason: "The deterministic payload marks event_data_known=false.",
          blocks_sizing: true,
          source: "synthesis.required_before_sizing",
        },
      ],
      rejected_ideas: [
        {
          idea_id: "C",
          structure: "long_straddle",
          reason: "No clear long-vol edge.",
        },
      ],
      missing_data: ["No event calendar data in deterministic payload."],
      rendering: {
        disclaimer:
          "Generated by local Codex from deterministic Trade Insights data. Not financial advice.",
        card_order: [],
      },
      guardrails: {
        statuses_preserved: true,
        risk_flags_preserved: true,
        no_executable_recommendations: true,
      },
    },
    markdown: "unused",
  };
}

function deferred<T>() {
  let resolve!: (value: T) => void;
  const promise = new Promise<T>((r) => {
    resolve = r;
  });
  return { promise, resolve };
}

describe("TradeInsightsAiAnalysisPanel", () => {
  beforeEach(() => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockReset();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(null);
  });

  it("shows the initial run control", () => {
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);
    expect(screen.getByText("AI ANALYSIS")).toBeDefined();
    expect(screen.getByText("Run AI Analysis")).toBeDefined();
  });

  it("keeps polling long enough for the deeper local Codex prompt", () => {
    expect(AI_ANALYSIS_POLL_MAX_MS).toBe(10 * 60 * 1000);
  });

  it("shows unavailable state when POST returns disabled", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockRejectedValueOnce(
      new Error("API 503 for /ai-analysis: disabled"),
    );
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);

    fireEvent.click(screen.getByText("Run AI Analysis"));

    expect(await screen.findByText(/not enabled/i)).toBeDefined();
  });

  it("runs, polls, and renders the structured card grid", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(baseResponse);
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockResolvedValueOnce(
      succeededResponse(),
    );
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);

    fireEvent.click(screen.getByText("Run AI Analysis"));

    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysis).toHaveBeenCalledWith("TSLA", {}),
    );
    expect(await screen.findByText("BUY setup")).toBeDefined();
    expect(
      screen.getByText(
        "TSLA near gamma resistance with cheap vol and bullish flow",
      ),
    ).toBeDefined();
    expect(screen.getByText("IV Rank")).toBeDefined();
    expect(screen.getByText("Break $382.50 wall")).toBeDefined();
    expect(screen.getByText("Market Structure")).toBeDefined();
    expect(screen.getByText("Volatility")).toBeDefined();
    expect(screen.getByText("Flow & Positioning")).toBeDefined();
    expect(screen.getByText("VRP Assessment")).toBeDefined();
    const cardGrid = screen.getByTestId("ai-analysis-card-grid");
    const topGrid = screen.getByTestId("ai-analysis-upper-card-grid");
    const lowerGrid = screen.getByTestId("ai-analysis-lower-card-grid");
    expect(topGrid.style.gridTemplateColumns).toBe(
      "repeat(3, minmax(0, 1fr))",
    );
    expect(lowerGrid.style.gridTemplateColumns).toBe(
      "minmax(0, 0.95fr) minmax(0, 0.9fr) minmax(0, 1.15fr)",
    );
    expect(cardGrid.style.gap).toBe("12px");
    expect(topGrid.style.alignItems).toBe("stretch");
    expect(lowerGrid.style.alignItems).toBe("stretch");
    expect(screen.getByText("Bull Call Spread - TSLA")).toBeDefined();
    expect(screen.getByText("Trade Setup Readiness")).toBeDefined();
    expect(screen.getByText("Validation Checklist")).toBeDefined();
    expect(screen.getByText("Price paths to watch")).toBeDefined();
    expect(screen.getByText("Must confirm before sizing")).toBeDefined();
    expect(screen.getAllByText("Confirm event calendar").length).toBeGreaterThan(0);
    expect(
      screen.getByText("No event calendar data in deterministic payload."),
    ).toBeDefined();
    expect(
      screen.getByText(/Generated analysis from local Codex/i),
    ).toBeDefined();
    expect(screen.getAllByText(/2026-03-24/).length).toBeGreaterThan(0);
  });

  it("hydrates the latest saved analysis under StrictMode effect replay", async () => {
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(
      succeededResponse(),
    );

    render(
      <StrictMode>
        <TradeInsightsAiAnalysisPanel ticker="TSLA" />
      </StrictMode>,
    );

    expect(
      await screen.findByText(
        "TSLA near gamma resistance with cheap vol and bullish flow",
      ),
    ).toBeDefined();
  });

  it("resumes polling the latest queued analysis after remount", async () => {
    const status = deferred<TradeInsightsAiAnalysisResponse>();
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValueOnce(baseResponse);
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValueOnce(
      status.promise,
    );

    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);

    expect(await screen.findByText(/AI analysis queued/i)).toBeDefined();
    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysisStatus).toHaveBeenCalledWith(
        "TSLA",
        baseResponse.analysis_id,
      ),
    );
    await act(async () => {
      status.resolve(succeededResponse());
      await status.promise;
    });
    expect(await screen.findByText("BUY setup")).toBeDefined();
    expect(api.tradeInsightsAiAnalysis).not.toHaveBeenCalled();
  });

  it("renders failed status with retry affordance", async () => {
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce({
      ...baseResponse,
      status: "failed",
      error_message: "codex timed out",
    });
    render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);

    fireEvent.click(screen.getByText("Run AI Analysis"));

    expect(await screen.findByText(/codex timed out/i)).toBeDefined();
    expect(screen.getByText("Retry")).toBeDefined();
  });

  it("ignores in-flight poll results after ticker changes", async () => {
    const status = deferred<TradeInsightsAiAnalysisResponse>();
    vi.mocked(api.tradeInsightsAiAnalysis).mockResolvedValueOnce(baseResponse);
    vi.mocked(api.tradeInsightsAiAnalysisStatus).mockReturnValueOnce(
      status.promise,
    );
    const { rerender } = render(<TradeInsightsAiAnalysisPanel ticker="TSLA" />);

    fireEvent.click(screen.getByText("Run AI Analysis"));
    await waitFor(() =>
      expect(api.tradeInsightsAiAnalysisStatus).toHaveBeenCalledWith(
        "TSLA",
        baseResponse.analysis_id,
      ),
    );

    rerender(<TradeInsightsAiAnalysisPanel ticker="AAPL" />);
    await act(async () => {
      status.resolve(succeededResponse());
      await status.promise;
    });

    expect(
      screen.queryByText(
        "TSLA near gamma resistance with cheap vol and bullish flow",
      ),
    ).toBeNull();
  });
});
