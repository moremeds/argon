/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidateStructuresPanel } from "@/components/stock/panels/CandidateStructuresPanel";
import { ChainFlowReadPanel } from "@/components/stock/panels/ChainFlowReadPanel";
import { InsightsSynthesisPanel } from "@/components/stock/panels/InsightsSynthesisPanel";
import { SignalStackPanel } from "@/components/stock/panels/SignalStackPanel";
import { SourceReconciliationPanel } from "@/components/stock/panels/SourceReconciliationPanel";
import { TermMovePanel } from "@/components/stock/panels/TermMovePanel";
import { TradeInsightsBiasBanner } from "@/components/stock/panels/TradeInsightsBiasBanner";

describe("TradeInsightsBiasBanner", () => {
  it("renders setup and badges without the ticker", () => {
    render(
      <TradeInsightsBiasBanner
        header={{
          dominant_bias: "NEUTRAL_SHORT_VOL",
          primary_setup: "TRADE_INSIGHTS_RESEARCH",
          confidence_label: "MEDIUM",
          data_quality_label: "MIXED",
          idea_count: 1,
          preferred_idea_id: null,
          badges: [{ code: "DEFINED_RISK_ONLY", label: "Defined-risk only", severity: "info" }],
        }}
      />,
    );
    // The parent layout's <DetailHeader> already renders the ticker, so the
    // banner intentionally does NOT — assert absence to lock that contract in.
    expect(screen.queryByText("TSLA")).toBeNull();
    expect(screen.getByText("TRADE_INSIGHTS_RESEARCH")).toBeDefined();
    expect(screen.getByText("Defined-risk only")).toBeDefined();
  });
});

describe("SourceReconciliationPanel", () => {
  it("renders source decision", () => {
    render(
      <SourceReconciliationPanel
        reconciliation={{
          status: "UNKNOWN",
          headline: "No external IV source reconciliation stored for this run",
          primary_iv_source: null,
          relative_shape_source: null,
          rows: [],
          decision: "Use chain-derived values for contract math.",
        }}
      />,
    );
    expect(screen.getByText(/chain-derived values/i)).toBeDefined();
  });
});

describe("SignalStackPanel", () => {
  it("renders lens rows", () => {
    render(
      <SignalStackPanel
        rows={[
          {
            lens: "VOL_LEVEL",
            read: "IV_RV_PROXY_AVAILABLE",
            evidence: ["proxy available"],
            conflicts: [],
          },
        ]}
      />,
    );
    expect(screen.getByText("VOL_LEVEL")).toBeDefined();
    expect(screen.getByText("proxy available")).toBeDefined();
  });
});

describe("Trade Insights detail panels", () => {
  it("renders flow table T+1 caveat", () => {
    render(
      <ChainFlowReadPanel
        rows={[
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
        ]}
      />,
    );
    expect(screen.getByText("CHAIN / FLOW HIGHLIGHTS")).toBeDefined();
    expect(screen.getByText("Call / Put volume")).toBeDefined();
    expect(screen.getByText(/next-day OI/i)).toBeDefined();
  });

  it("renders term move rows", () => {
    render(
      <TermMovePanel
        rows={[
          {
            expiry: "2026-05-15",
            dte: 4,
            atm_straddle: null,
            implied_move_perc: "0.048",
            daily_implied_move_perc: "0.012",
            read: "Front elevated",
          },
        ]}
      />,
    );
    expect(screen.getByText("TERM / MOVE HIGHLIGHTS")).toBeDefined();
    expect(screen.getByText("Curve read")).toBeDefined();
    expect(screen.getByText("2026-05-15")).toBeDefined();
    expect(screen.getByText("Front elevated")).toBeDefined();
  });

  it("renders candidate max loss", () => {
    render(
      <CandidateStructuresPanel
        candidates={[
          {
            idea_id: "A",
            structure: "call_credit_spread",
            thesis: "Defined-risk short-call premium candidate.",
            expression_type: "SHORT_VOL",
            legs: [],
            net_credit_debit: "1.25",
            max_profit: "1.25",
            max_loss: "3.75",
            breakevens: [],
            profit_zone: "Underlying below 430",
            edge_source: "IV-RV spread / theta",
            risk_flags: ["bullish_flow_can_break_call_side"],
            rank: 1,
            status: "candidate",
          },
        ]}
      />,
    );
    expect(screen.getByText(/Max loss/i)).toBeDefined();
    expect(screen.getByText("$3.75")).toBeDefined();
  });

  it("renders synthesis required checks", () => {
    render(
      <InsightsSynthesisPanel
        synthesis={{
          dominant_story: "Research-grade ideas built from current chain.",
          preferred_idea_id: "A",
          best_risk_reward_idea_id: "A",
          avoid: ["Naked short options"],
          required_before_sizing: ["Confirm event calendar"],
        }}
      />,
    );
    expect(screen.getByText(/Confirm event calendar/)).toBeDefined();
  });
});
