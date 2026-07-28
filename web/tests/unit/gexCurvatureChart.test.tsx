/* @vitest-environment jsdom */
import { fireEvent, render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import GexCurvatureChart from "@/components/shared/GexCurvatureChart";
import type { GexBucket } from "@/lib/regime/useGex";

function b(
  strike: number,
  net_gex: number,
  tag: string | null = null,
): GexBucket {
  return { strike, call_gex: 0, put_gex: 0, net_gex, pct_from_spot: 0, tag };
}

const wide = [
  b(90, -5_000),
  b(95, -3_000),
  b(100, 1_000),
  b(105, 4_000),
  b(110, 6_000),
];

describe("GexCurvatureChart", () => {
  it("renders the flip rule from the explicit prop when no strike is tagged", () => {
    // The flip is an interpolated zero-crossing: 97.5 is not a listed strike,
    // so a tag-match-only implementation would silently drop the rule.
    render(<GexCurvatureChart profile={wide} spot={100} flipStrike={97.5} />);
    expect(screen.getByText(/FLIP 97.5/)).not.toBeNull();
  });

  it("prefers the explicit flip prop over a tagged bucket", () => {
    const tagged = [
      ...wide.slice(0, 2),
      b(100, 1_000, "GEX FLIP"),
      ...wide.slice(3),
    ];
    render(<GexCurvatureChart profile={tagged} spot={100} flipStrike={97.5} />);
    expect(screen.getByText(/FLIP 97.5/)).not.toBeNull();
  });

  it("survives the profile shrinking under a stale hover index", () => {
    // Regression: hoverIdx is state, but the profile is re-polled underneath
    // it. Hovering the far-right point and then shrinking the profile left a
    // dangling index — points[hoverIdx][0] threw and blanked the panel.
    const { rerender, container } = render(
      <GexCurvatureChart profile={wide} spot={100} />,
    );
    const svg = container.querySelector("svg")!;
    // jsdom reports a zero-size rect, which makes onMove's px arithmetic
    // divide by zero and bail — stub a real one so the handler runs and
    // actually parks hoverIdx on the last bucket (index 4).
    svg.getBoundingClientRect = () =>
      ({ left: 0, top: 0, width: 1000, height: 320 }) as DOMRect;
    fireEvent.mouseMove(svg, { clientX: 900, clientY: 100 });

    expect(() =>
      rerender(<GexCurvatureChart profile={wide.slice(0, 2)} spot={100} />),
    ).not.toThrow();
    // Still rendering a chart, not an error boundary.
    expect(screen.getByText(/curvature field by strike/i)).not.toBeNull();
  });

  it("gives each instance its own clip-path ids", () => {
    // SVG ids are document-global; two charts sharing #gex-above would make
    // the first instance's clip win for both.
    const { container } = render(
      <>
        <GexCurvatureChart profile={wide} spot={100} />
        <GexCurvatureChart profile={wide} spot={100} />
      </>,
    );
    const ids = Array.from(container.querySelectorAll("clipPath")).map(
      (n) => n.id,
    );
    expect(ids).toHaveLength(4);
    expect(new Set(ids).size).toBe(4);
  });

  it("falls back to an empty state below two strikes", () => {
    render(<GexCurvatureChart profile={[b(100, 1)]} spot={100} />);
    expect(screen.getByText(/Not enough strikes/)).not.toBeNull();
  });
});
