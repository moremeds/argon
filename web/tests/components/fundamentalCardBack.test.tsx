import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FundamentalCardBack } from "@/components/stock/panels/FundamentalCardBack";

const PERIODS = [
  "2025-04-30",
  "2025-07-31",
  "2025-10-31",
  "2026-01-31",
  "2026-04-30",
];
const REV = [44062000000, 46743000000, 57006000000, 68127000000, 81615000000];
const GP = [26668000000, 33853000000, 41849000000, 51093000000, 61157000000];

const detail = {
  feature: "gross_margin",
  basis: "quarterly",
  unit: "ratio",
  series: [
    {
      key: "gross_profit",
      label: "gross profit",
      role: "input",
      unit: "currency",
      values: GP,
    },
    {
      key: "total_revenue",
      label: "revenue",
      role: "input",
      unit: "currency",
      values: REV,
    },
  ],
  ratio: GP.map((g, i) => g / REV[i]),
};

const props = {
  detail,
  periods: PERIODS,
  currency: "USD",
  label: "Gross margin",
};

describe("FundamentalCardBack", () => {
  it("states the basis, because it is not uniform across features", () => {
    render(<FundamentalCardBack {...props} />);
    expect(screen.getByText(/quarterly/)).toBeTruthy();
  });

  it("states the reported currency", () => {
    // TSM files TWD against a USD quote; an unlabelled axis is how that becomes
    // a wrong number that looks right.
    render(<FundamentalCardBack {...props} />);
    expect(screen.getByText(/USD/)).toBeTruthy();
  });

  it("renders a TWD fixture as TWD", () => {
    render(<FundamentalCardBack {...props} currency="TWD" />);
    expect(screen.getByText(/TWD/)).toBeTruthy();
  });

  it("labels each series", () => {
    render(<FundamentalCardBack {...props} />);
    expect(screen.getByText("gross profit")).toBeTruthy();
    expect(screen.getByText("revenue")).toBeTruthy();
  });

  it("gives a no-direction feature a neutral ratio stroke", () => {
    // gross_margin measured INVERTED; the back must not undo the front's rule.
    const { container } = render(<FundamentalCardBack {...props} />);
    const stroke = container
      .querySelector("path[data-ratio]")
      ?.getAttribute("stroke");
    expect(stroke).toBe("var(--text-secondary)");
  });

  it("gives a directional feature its own stroke", () => {
    const { container } = render(
      <FundamentalCardBack
        {...props}
        detail={{ ...detail, feature: "fcf_margin" }}
        label="FCF margin"
      />,
    );
    expect(
      container.querySelector("path[data-ratio]")?.getAttribute("stroke"),
    ).toBe("var(--accent-bg)");
  });

  it("renders no control of its own — the card it sits in is the control", () => {
    // The wrapper is a <button>, so anything interactive in here would be a
    // button inside a button: invalid HTML, and browsers recover from it by
    // reparenting the DOM, which silently breaks the layout. The way back is a
    // hint, not a control.
    render(<FundamentalCardBack {...props} />);
    expect(screen.queryByRole("button")).toBeNull();
    expect(screen.getByText(/click to flip back/i)).toBeTruthy();
  });
});
