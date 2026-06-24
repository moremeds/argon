/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import MacroShortVolSizingTable from "@/components/regime/MacroShortVolSizingTable";

describe("MacroShortVolSizingTable", () => {
  it("renders the SPX-direct sizing guidance rows", () => {
    render(<MacroShortVolSizingTable />);
    expect(screen.getByText(/SIZING GUIDANCE/i)).toBeTruthy();
    // CAGR-gross column is unique per row (not echoed in the footnotes)
    expect(screen.getByText("14.2%")).toBeTruthy(); // base_risk_pct 0.20
    expect(screen.getByText("16.6%")).toBeTruthy(); // base_risk_pct 0.32
    expect(screen.getByText("17.7%")).toBeTruthy(); // base_risk_pct 0.50
  });
});
