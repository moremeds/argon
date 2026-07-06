/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PositionsPanel } from "@/components/positions/PositionsPanel";
import { PnlChart } from "@/components/positions/PnlChart";
import type { components } from "@/lib/types";

type PositionRow = components["schemas"]["VrpMacroPositionRow"];

function row(over: Partial<PositionRow> = {}): PositionRow {
  return {
    entry_id: 42,
    name: "SPX",
    origin: "auto",
    birth_date: "2026-06-24",
    born_at: "2026-06-24T14:00:00Z",
    expiry: "2026-08-07",
    hold_days: 30,
    action_at_birth: "TRADE",
    vrp_z_at_birth: "0.6",
    weight_at_birth: "1.0",
    spot_at_birth: "6000",
    short_strike: "5800",
    wing_strike: "5600",
    width: "200",
    status: "open",
    dte: 33,
    days_held: 11,
    n_marks: 12,
    entry_credit: "8.0",
    current_value: "4.0",
    unrealized_pnl: "4.0",
    max_loss: "192.0",
    return_on_risk: "0.0208",
    last_mark_at: "2026-07-05T14:00:00Z",
    last_spot: "6050",
    ...over,
  };
}

describe("PositionsPanel", () => {
  it("renders a cohort row with credit, P&L, and open status", () => {
    render(<PositionsPanel positions={[row()]} />);
    expect(screen.getByText(/#42/)).toBeDefined();
    expect(screen.getByText(/OPEN · 33d/)).toBeDefined();
    expect(screen.getByText("8.00")).toBeDefined(); // entry credit
    expect(screen.getByText("+4.00")).toBeDefined(); // unrealized P&L
  });

  it("shows expired status when past expiry", () => {
    render(
      <PositionsPanel positions={[row({ status: "expired", dte: -3 })]} />,
    );
    expect(screen.getByText("EXPIRED")).toBeDefined();
  });

  it("shows an empty state when there are no positions", () => {
    render(<PositionsPanel positions={[]} />);
    expect(screen.getByText(/No captured VRP-macro positions yet/i)).toBeDefined();
  });
});

describe("PnlChart", () => {
  it("renders an SVG curve when there are enough marks", () => {
    const { container } = render(<PnlChart pnl={[0, 1.5, 4.0]} />);
    expect(container.querySelector("svg")).not.toBeNull();
    expect(container.querySelector("path")).not.toBeNull();
  });

  it("shows an empty-state note with too few marks", () => {
    render(<PnlChart pnl={[null]} />);
    expect(screen.getByText(/Not enough marks/i)).toBeDefined();
  });
});
