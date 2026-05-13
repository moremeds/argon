import { render } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FlowTimelinePanel } from "@/components/stock/panels/FlowTimelinePanel";

describe("FlowTimelinePanel", () => {
  const dates = ["2026-05-09", "2026-05-10", "2026-05-11", "2026-05-12"];

  it("renders both series paths in SVG", () => {
    const { container } = render(
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{
          label: "Volume",
          values: [1000, 1500, 2000, 1200],
          color: "var(--accent-bg)",
        }}
        secondary={{
          label: "P/C",
          values: [0.6, 0.8, 0.9, 0.7],
          color: "var(--accent-warm)",
        }}
        dates={dates}
      />,
    );
    const paths = container.querySelectorAll("svg path");
    expect(paths.length).toBeGreaterThanOrEqual(2);
  });

  it("renders earnings marker lines when supplied", () => {
    const { container } = render(
      <FlowTimelinePanel
        title="OPTIONS VOLUME"
        primary={{
          label: "Volume",
          values: [1000, 1500, 2000, 1200],
          color: "var(--accent-bg)",
        }}
        secondary={{
          label: "P/C",
          values: [0.6, 0.8, 0.9, 0.7],
          color: "var(--accent-warm)",
        }}
        dates={dates}
        markers={["2026-05-10"]}
      />,
    );
    const markerLines = container.querySelectorAll(
      "[data-testid='earnings-marker']",
    );
    expect(markerLines.length).toBe(1);
  });

  it("renders NO DATA when fewer than 2 finite values are present", () => {
    const { container } = render(
      <FlowTimelinePanel
        title="OI"
        primary={{
          label: "OI",
          values: [1000, null],
          color: "var(--accent-bg)",
        }}
        secondary={{
          label: "P/C OI",
          values: [0.6, 0.8],
          color: "var(--accent-warm)",
        }}
        dates={["2026-05-09", "2026-05-10"]}
      />,
    );
    expect(container.textContent).toMatch(/NO DATA/);
  });
});
