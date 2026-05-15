import { fireEvent, render, screen } from "@testing-library/react";
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
  it("renders premium, dark-pool, and short-interest labels without the capped alert card", () => {
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
    expect(screen.queryByText("Alerts")).toBeNull();
  });

  it("reveals tooltip definition + benchmark on hover, hides on mouseleave", () => {
    render(
      <FlowSnapshotGrid
        flow={FIXTURE_FLOW}
        darkPool={{ prints: 0, notional: null }}
        shortData={null}
      />,
    );
    // Closed by default — hover-gated.
    expect(screen.queryByText(/aggregate alert flow/)).toBeNull();

    const trigger = screen.getByLabelText("Net Premium explanation")
      .parentElement as HTMLElement;
    fireEvent.mouseEnter(trigger);
    expect(screen.getByText(/aggregate alert flow/)).toBeTruthy();
    expect(screen.getByText(/bull\/bear ratio/)).toBeTruthy();

    fireEvent.mouseLeave(trigger);
    expect(screen.queryByText(/aggregate alert flow/)).toBeNull();
  });
});
