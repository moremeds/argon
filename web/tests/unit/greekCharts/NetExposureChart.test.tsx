import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { NetExposureChart } from "@/components/stock/panels/greeks/NetExposureChart";

const curve = [
  { strike: 90, netValue: -100 },
  { strike: 100, netValue: -50 },
  { strike: 110, netValue: 200 },
  { strike: 120, netValue: 250 },
];

describe("NetExposureChart", () => {
  it("draws a path covering all finite points", () => {
    const { container } = render(
      <NetExposureChart
        curve={curve}
        spot={105}
        flipStrike={110}
        yLabel="Vanna"
        title="Net Vanna Exposure (9 DTE) — TSLA"
      />,
    );
    const path = container.querySelector("path[data-testid='net-line']");
    expect(path).not.toBeNull();
    const d = path!.getAttribute("d") ?? "";
    expect(d.startsWith("M")).toBe(true);
    expect(d.match(/L/g)?.length ?? 0).toBeGreaterThanOrEqual(3);
  });

  it("renders the spot reference line", () => {
    const { container } = render(
      <NetExposureChart
        curve={curve}
        spot={105}
        flipStrike={null}
        yLabel="Vanna"
        title="x"
      />,
    );
    expect(
      container.querySelector("line[data-testid='spot-line']"),
    ).not.toBeNull();
  });

  it("renders the flip reference line when flipStrike provided", () => {
    const { container } = render(
      <NetExposureChart
        curve={curve}
        spot={105}
        flipStrike={110}
        yLabel="Vanna"
        title="x"
      />,
    );
    expect(
      container.querySelector("line[data-testid='flip-line']"),
    ).not.toBeNull();
  });

  it("renders empty state when curve has zero finite points", () => {
    const { container, queryByText } = render(
      <NetExposureChart
        curve={[]}
        spot={105}
        flipStrike={null}
        yLabel="Vanna"
        title="x"
      />,
    );
    expect(container.querySelector("path[data-testid='net-line']")).toBeNull();
    expect(queryByText(/not enough/i)).not.toBeNull();
  });

  it("renders a single-point marker (no line) when curve has exactly one finite point", () => {
    const { container, queryByText } = render(
      <NetExposureChart
        curve={[{ strike: 100, netValue: 5000 }]}
        spot={100}
        flipStrike={null}
        yLabel="Vanna"
        title="x"
      />,
    );
    expect(queryByText(/not enough/i)).toBeNull();
    expect(
      container.querySelector("circle[data-testid='net-point']"),
    ).not.toBeNull();
    expect(
      container.querySelector("line[data-testid='spot-line']"),
    ).not.toBeNull();
  });
});
