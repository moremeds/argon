import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it } from "vitest";

import {
  MultiLineChart,
  normalizeChartSeries,
  type ChartSeries,
} from "@/app/cockpit/[ticker]/CockpitChart";

afterEach(() => {
  cleanup();
});

describe("normalizeChartSeries", () => {
  const unsorted: ChartSeries[] = [
    {
      label: "line",
      color: "red",
      points: [
        { x: 3, y: 30 },
        { x: 1, y: 10 },
        { x: 2, y: null },
        { x: Number.NaN, y: 20 },
      ],
    },
  ];

  it("drops invalid points and sorts by x by default", () => {
    expect(normalizeChartSeries(unsorted)[0].points).toEqual([
      { x: 1, y: 10 },
      { x: 3, y: 30 },
    ]);
  });

  it("preserves valid input order when assumeSorted is set", () => {
    expect(normalizeChartSeries(unsorted, true)[0].points).toEqual([
      { x: 3, y: 30 },
      { x: 1, y: 10 },
    ]);
  });
});

describe("MultiLineChart", () => {
  it("renders NO DATA for empty normalized series", () => {
    render(
      <MultiLineChart
        series={[
          {
            label: "empty",
            color: "red",
            points: [{ x: 1, y: null }],
          },
        ]}
      />,
    );

    expect(screen.getByText("NO DATA")).toBeTruthy();
  });

  it("renders finite SVG coordinates for finite data", () => {
    const { container } = render(
      <MultiLineChart
        series={[
          {
            label: "line",
            color: "red",
            points: [
              { x: 2, y: 10 },
              { x: 1, y: 5 },
            ],
          },
        ]}
      />,
    );

    const polyline = container.querySelector("polyline");
    expect(polyline).toBeTruthy();
    const points = polyline?.getAttribute("points") ?? "";
    expect(points).not.toContain("NaN");
    expect(points).not.toContain("Infinity");
    expect(points).toMatch(/\d/);
  });

  it("keeps single-x and single-y data finite", () => {
    const { container } = render(
      <MultiLineChart
        showZero={false}
        series={[
          {
            label: "single",
            color: "red",
            points: [{ x: 1, y: 5 }],
          },
        ]}
      />,
    );

    const points = container.querySelector("polyline")?.getAttribute("points");
    expect(points).toBeTruthy();
    expect(points).not.toContain("NaN");
    expect(points).not.toContain("Infinity");
  });
});
