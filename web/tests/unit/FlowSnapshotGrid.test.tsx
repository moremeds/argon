import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlowSnapshotGrid } from "@/components/stock/panels/FlowSnapshotGrid";

const FIXTURE_FLOW = {
  ticker: "GOOGL",
  flow_count: 100,
  net_premium: "62000000",
  bull_premium: "66000000",
  bear_premium: "4000000",
  ask_side_premium: "30000000",
  bid_side_premium: "35000000",
  top_alerts: [],
} as unknown as Parameters<typeof FlowSnapshotGrid>[0]["flow"];

describe("FlowSnapshotGrid", () => {
  it("renders all 11 snapshot tile labels", () => {
    render(
      <FlowSnapshotGrid
        flow={FIXTURE_FLOW}
        darkPool={{ prints: 481, notional: "115000000" }}
        shortData={
          {
            symbol: "GOOGL",
            timestamp: "2026-05-13T12:00:00Z",
            short_shares_available: 10_000_000,
            fee_rate: "0.25",
            rebate_rate: "3.38",
          } as never
        }
      />,
    );

    // Labels are stored Title Case in the DOM; CSS text-transform uppercases
    // them visually.
    for (const label of [
      "Alerts",
      "Net Premium",
      "Bull Premium",
      "Bear Premium",
      "Ask Premium",
      "Bid Premium",
      "DP Prints",
      "DP Notional",
      "Shares Avail",
      "Fee Rate",
      "Rebate Rate",
    ]) {
      expect(screen.getByText(label)).toBeTruthy();
    }
  });

  it("shows tooltip definition + benchmark in the DOM", () => {
    render(
      <FlowSnapshotGrid
        flow={FIXTURE_FLOW}
        darkPool={{ prints: 0, notional: null }}
        shortData={null}
      />,
    );
    expect(screen.getByText(/UW flow alerts/)).toBeTruthy();
    expect(screen.getByText(/Median active ticker/)).toBeTruthy();
  });
});
