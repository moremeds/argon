/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { SignalStackPanel } from "@/components/stock/panels/SignalStackPanel";
import { SourceReconciliationPanel } from "@/components/stock/panels/SourceReconciliationPanel";
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
