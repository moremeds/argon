import { fireEvent, render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { GreekSubTabs } from "@/components/stock/panels/greeks/GreekSubTabs";

const fakeReport = {
  ticker: "TSLA",
  strike_gex_curve: [],
  market_structure: { spot: "100" },
  market_structure_levels: null,
  strike_exposures: [],
  exposures_summary: [],
} as never;

describe("GreekSubTabs", () => {
  it("renders GEX panel by default", () => {
    const { getByText, queryByText } = render(
      <GreekSubTabs report={fakeReport} />,
    );
    expect(getByText("GEX").getAttribute("aria-selected")).toBe("true");
    expect(queryByText(/Vanna data not yet available/)).toBeNull();
    expect(queryByText(/Charm data not yet available/)).toBeNull();
  });

  it("switches to Vanna sub-tab on click", () => {
    const { getByText } = render(<GreekSubTabs report={fakeReport} />);
    fireEvent.click(getByText("VANNA"));
    expect(getByText("VANNA").getAttribute("aria-selected")).toBe("true");
    expect(getByText(/Vanna data not yet available/)).toBeTruthy();
  });

  it("switches to Charm sub-tab on click", () => {
    const { getByText } = render(<GreekSubTabs report={fakeReport} />);
    fireEvent.click(getByText("CHARM"));
    expect(getByText(/Charm data not yet available/)).toBeTruthy();
  });
});
