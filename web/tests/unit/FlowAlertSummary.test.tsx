import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlowAlertSummary } from "@/components/stock/panels/FlowAlertSummary";

const FLOW = {
  ticker: "GOOGL",
  flow_count: 100,
  flow_count_is_limited: true,
  flow_count_30d_avg: "35.5",
  flow_count_vs_30d_avg: "2.8169",
  flow_count_30d_days: 20,
  net_premium: "62000000",
  bull_premium: "66000000",
  bear_premium: "4000000",
  ask_side_premium: "30000000",
  bid_side_premium: "15000000",
  top_alerts: [
    { id: "1", alert_rule: "RepeatedHits", total_premium: "4455000" },
    { id: "2", alert_rule: "FloorTradeLargeCap", total_premium: "100000" },
  ],
};

describe("FlowAlertSummary", () => {
  it("renders capped alert count, top rule, premium, ask/bid ratio, and baseline", () => {
    render(<FlowAlertSummary flow={FLOW as never} />);

    expect(screen.getByText("100+ alerts fetched")).toBeTruthy();
    expect(screen.getByText("Top rule RepeatedHits")).toBeTruthy();
    expect(screen.getByText("Premium $70,000,000")).toBeTruthy();
    expect(screen.getByText("Ask/Bid 2.0x")).toBeTruthy();
    const baseline = screen.getByText("Alerts >=2.8x 30d avg");
    expect(baseline).toBeTruthy();
    expect(baseline.getAttribute("data-highlight")).toBe("baseline");
  });
});
