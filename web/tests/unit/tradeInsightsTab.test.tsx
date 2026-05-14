/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { TradeInsightsTab } from "@/components/stock/tabs/TradeInsightsTab";
import { api, type TradeInsightsResponse } from "@/lib/api";

vi.mock("@/lib/api", async () => {
  return {
    api: {
      tradeInsights: vi.fn(),
      tradeInsightsAiAnalysisLatest: vi.fn(),
    },
  };
});

function mockInsights(): TradeInsightsResponse {
  return {
    ticker: "TSLA",
    mode: "research",
    header: {
      dominant_bias: "NEUTRAL_SHORT_VOL",
      primary_setup: "TRADE_INSIGHTS_RESEARCH",
      confidence_label: "MEDIUM",
      data_quality_label: "MIXED",
      idea_count: 0,
      preferred_idea_id: null,
      badges: [],
    },
    source_reconciliation: {
      status: "UNKNOWN",
      headline: "No external IV source reconciliation stored for this run",
      primary_iv_source: null,
      relative_shape_source: null,
      rows: [],
      decision: "Use chain-derived values for contract math.",
    },
    signal_stack: [],
    candidate_structures: [],
    synthesis: {
      dominant_story: "Research-grade ideas built from current chain.",
      preferred_idea_id: null,
      best_risk_reward_idea_id: null,
      avoid: [],
      required_before_sizing: ["Confirm event calendar"],
    },
    flow_table: [
      {
        strike: "430",
        call_volume: 1500,
        call_open_interest: 1000,
        put_volume: 600,
        put_open_interest: 700,
        call_put_volume_ratio: "2.5",
        volume_oi_note: "Volume > OI; confirm with next-day OI",
        read: "Call demand concentrated",
        requires_t1_oi_confirmation: true,
      },
    ],
    term_structure_table: [
      {
        expiry: "2026-05-15",
        dte: 4,
        atm_straddle: null,
        implied_move_perc: "0.048",
        daily_implied_move_perc: "0.012",
        read: "Front elevated",
      },
    ],
  } as TradeInsightsResponse;
}

function comesBefore(a: HTMLElement, b: HTMLElement): boolean {
  return Boolean(a.compareDocumentPosition(b) & Node.DOCUMENT_POSITION_FOLLOWING);
}

describe("TradeInsightsTab", () => {
  beforeEach(() => {
    vi.mocked(api.tradeInsights).mockResolvedValue(mockInsights());
    vi.mocked(api.tradeInsightsAiAnalysisLatest).mockResolvedValue(null);
  });

  it("orders header, AI analysis, evidence highlights, then deterministic decision panels", async () => {
    render(await TradeInsightsTab({ ticker: "TSLA" }));

    const header = screen.getByText("Trade Insights Research");
    const synthesis = screen.getByText("SYNTHESIS");
    const candidates = screen.getByText("CANDIDATE STRUCTURES");
    const aiAnalysis = screen.getByText("AI ANALYSIS");
    const flowHighlights = screen.getByText("CHAIN / FLOW HIGHLIGHTS");
    const termHighlights = screen.getByText("TERM / MOVE HIGHLIGHTS");
    const sourceReconciliation = screen.getByText("SOURCE RECONCILIATION");
    const signalStack = screen.getByText("SIGNAL STACK");
    const evidenceGrid = screen.getByTestId("trade-insights-evidence-grid");

    expect(comesBefore(header, aiAnalysis)).toBe(true);
    expect(comesBefore(aiAnalysis, flowHighlights)).toBe(true);
    expect(comesBefore(flowHighlights, termHighlights)).toBe(true);
    expect(comesBefore(termHighlights, sourceReconciliation)).toBe(true);
    expect(comesBefore(sourceReconciliation, signalStack)).toBe(true);
    expect(comesBefore(signalStack, synthesis)).toBe(true);
    expect(comesBefore(synthesis, candidates)).toBe(true);
    expect(evidenceGrid.className).toBe("trade-insights-evidence-grid");
  });
});
