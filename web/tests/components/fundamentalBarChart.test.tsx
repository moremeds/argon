import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FundamentalBarChart } from "@/components/stock/panels/FundamentalBarChart";

// NVDA's real last five fiscal quarters, frozen 2026-08-12.
const PERIODS = [
  "2025-04-30",
  "2025-07-31",
  "2025-10-31",
  "2026-01-31",
  "2026-04-30",
];
const REV = [44062000000, 46743000000, 57006000000, 68127000000, 81615000000];
const GP = [26668000000, 33853000000, 41849000000, 51093000000, 61157000000];

const props = {
  periods: PERIODS,
  series: [
    { key: "gross_profit", label: "gross profit", role: "input", values: GP },
    { key: "total_revenue", label: "revenue", role: "input", values: REV },
  ],
  ratio: GP.map((g, i) => g / REV[i]),
  ratioUnit: "ratio" as const,
};

describe("FundamentalBarChart", () => {
  it("draws one bar per period per series", () => {
    const { container } = render(<FundamentalBarChart {...props} />);
    expect(container.querySelectorAll("rect[data-series]")).toHaveLength(10);
  });

  it("marks context series distinctly from inputs", () => {
    // Load-bearing: a context field is NOT part of the ratio, so it must not
    // read as one of the figures the line was computed from.
    const { container } = render(
      <FundamentalBarChart
        {...props}
        series={[
          ...props.series,
          {
            key: "cost_of_revenue",
            label: "cost of revenue",
            role: "context",
            values: REV.map((r, i) => r - GP[i]),
          },
        ]}
      />,
    );
    const ctx = container.querySelectorAll('rect[data-role="context"]');
    expect(ctx).toHaveLength(5);
    expect(ctx[0].getAttribute("fill-opacity")).toBe("0.35");
  });

  it("draws a gap rather than interpolating a null period", () => {
    const withGap = { ...props, ratio: [0.6, null, 0.73, 0.75, 0.749] };
    const { container } = render(<FundamentalBarChart {...withGap} />);
    const d =
      container.querySelector("path[data-ratio]")?.getAttribute("d") ?? "";
    expect((d.match(/M/g) ?? []).length).toBeGreaterThan(1);
  });

  it("omits a bar for a null value instead of drawing zero", () => {
    const withNull = {
      ...props,
      series: [
        {
          key: "gross_profit",
          label: "gross profit",
          role: "input",
          values: [null, ...GP.slice(1)],
        },
      ],
    };
    const { container } = render(<FundamentalBarChart {...withNull} />);
    expect(container.querySelectorAll("rect[data-series]")).toHaveLength(4);
  });

  it("is labelled for assistive tech", () => {
    const { container } = render(<FundamentalBarChart {...props} />);
    const svg = container.querySelector("svg");
    expect(svg?.getAttribute("role")).toBe("img");
    expect(container.querySelector("title")?.textContent).toBeTruthy();
  });
});
