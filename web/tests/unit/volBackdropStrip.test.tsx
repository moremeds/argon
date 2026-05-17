/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { VolBackdropStripView } from "@/components/regime/VolBackdropStrip";

const sample = {
  series: {
    VIX: [
      { date: "2026-05-14", close: 18.1 },
      { date: "2026-05-15", close: 18.4 },
    ],
    VIX3M: [
      { date: "2026-05-14", close: 21.0 },
      { date: "2026-05-15", close: 21.4 },
    ],
    VVIX: [
      { date: "2026-05-14", close: 92.1 },
      { date: "2026-05-15", close: 92.9 },
    ],
    COR1M: [
      { date: "2026-05-14", close: 10.5 },
      { date: "2026-05-15", close: 10.8 },
    ],
  },
  term_structure_ratio: 0.86,
  term_structure_state: "contango" as const,
  as_of: "2026-05-15",
};

describe("VolBackdropStripView", () => {
  it("renders all four tiles", () => {
    render(<VolBackdropStripView data={sample} />);
    expect(screen.getByText("VIX")).toBeTruthy();
    expect(screen.getByText("VIX3M")).toBeTruthy();
    expect(screen.getByText("VVIX")).toBeTruthy();
    expect(screen.getByText("COR1M")).toBeTruthy();
  });

  it("shows term-structure state badge", () => {
    render(<VolBackdropStripView data={sample} />);
    expect(screen.getByText(/contango/i)).toBeTruthy();
  });

  it("renders nothing when data is null", () => {
    const { container } = render(<VolBackdropStripView data={null} />);
    expect(container.firstChild).toBeNull();
  });
});
