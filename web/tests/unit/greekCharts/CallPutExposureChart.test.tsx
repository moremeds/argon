import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { CallPutExposureChart } from "@/components/stock/panels/greeks/CallPutExposureChart";

const curve = [
  { strike: 90, callValue: 100, putValue: -50 },
  { strike: 100, callValue: 200, putValue: -100 },
  { strike: 110, callValue: 80, putValue: -150 },
];

describe("CallPutExposureChart", () => {
  it("draws two paths", () => {
    const { container } = render(
      <CallPutExposureChart
        curve={curve}
        spot={100}
        yLabel="Vanna"
        title="Vanna Exposure — TSLA"
      />,
    );
    expect(
      container.querySelector("path[data-testid='call-line']"),
    ).not.toBeNull();
    expect(
      container.querySelector("path[data-testid='put-line']"),
    ).not.toBeNull();
  });

  it("renders the spot reference line", () => {
    const { container } = render(
      <CallPutExposureChart
        curve={curve}
        spot={100}
        yLabel="Vanna"
        title="x"
      />,
    );
    expect(
      container.querySelector("line[data-testid='spot-line']"),
    ).not.toBeNull();
  });

  it("renders empty state when curve is empty", () => {
    const { container, queryByText } = render(
      <CallPutExposureChart curve={[]} spot={null} yLabel="Vanna" title="x" />,
    );
    expect(container.querySelector("path[data-testid='call-line']")).toBeNull();
    expect(queryByText(/not enough/i)).not.toBeNull();
  });
});
