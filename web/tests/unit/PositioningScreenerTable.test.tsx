/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PositioningScreenerTable } from "@/components/positioning/PositioningScreenerTable";

describe("PositioningScreenerTable", () => {
  it("renders a row with squeeze label, %float and insider tilt", () => {
    render(
      <PositioningScreenerTable
        rows={[
          {
            ticker: "HIMS",
            snapshot_date: "2026-07-06",
            spot: "20",
            si_pct_float: "0.29",
            si_days_to_cover: "3.53",
            si_fee_rate: "0.45",
            squeeze_score: 3,
            squeeze_label: "ELEVATED",
            insider_net_flow: "753258606",
            insider_tilt: "BUYING",
            analyst_implied_upside_pct: "27.38",
            er_positive_base_rate: "0",
            days_to_next_er: 26,
          },
        ]}
      />,
    );
    expect(screen.getByText("HIMS")).toBeDefined();
    expect(screen.getByText("ELEVATED")).toBeDefined();
    // 0.29 fraction -> 29.0%
    expect(screen.getByText("29.0%")).toBeDefined();
    // insider $ flow humanized to millions (1-decimal in the table)
    expect(screen.getByText("$753.3M")).toBeDefined();
    expect(screen.getByText("+27.4%")).toBeDefined();
  });

  it("shows an empty-state message when there are no rows", () => {
    render(<PositioningScreenerTable rows={[]} />);
    expect(screen.getByText(/No positioning snapshots banked/)).toBeDefined();
  });
});
