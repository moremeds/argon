import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { GammaBars } from "@/components/flash/GammaBars";
import { PayoffChart } from "@/components/flash/PayoffChart";
import type { CandidateView } from "@/components/flash/view";

/** `QQQ-2026-09-03-1`, the recorded 710/665 put debit spread. */
const QQQ: CandidateView = {
  id: "QQQ-2026-09-03-1",
  ticker: "QQQ",
  strategy: "put_debit_spread",
  expiry: "2026-10-02",
  dte: 29,
  spot: 717.47,
  width: 45,
  legs: [
    { action: "buy", right: "put", strike: 710, expiry: "2026-10-02", mid: 10.45 },
    { action: "sell", right: "put", strike: 665, expiry: "2026-10-02", mid: 2.71 },
  ],
  pricing: {
    kind: "priced",
    net: 7.74,
    maxGain: 3726,
    maxLoss: 774,
    breakevens: [702.26],
    pnlAt: [],
  },
};

describe("PayoffChart", () => {
  it("names the structure, its bounds and its breakeven in the aria-label", () => {
    render(<PayoffChart candidate={QQQ} />);

    const label = screen.getByRole("img").getAttribute("aria-label") ?? "";
    expect(label).toContain("QQQ");
    expect(label).toContain("702.26");
    expect(label).toContain("3726");
    expect(label).toContain("774");
    // A put debit spread gains BELOW its breakeven. The preposition is derived
    // from the curve, not hard-coded — a call spread would read the other way.
    expect(label).toMatch(/gain 3726 dollars below/);
  });

  it("labels breakeven and spot in text, never by colour alone", () => {
    const { container } = render(<PayoffChart candidate={QQQ} />);

    expect(screen.getByText("BE 702.26")).toBeTruthy();
    expect(screen.getByText("SPOT 717.47")).toBeTruthy();
    expect(
      container.querySelectorAll("line[stroke-dasharray]").length,
    ).toBeGreaterThanOrEqual(2);
  });

  it("ticks both strikes inside the domain", () => {
    render(<PayoffChart candidate={QQQ} />);

    expect(screen.getByText("710.00")).toBeTruthy();
    expect(screen.getByText("665.00")).toBeTruthy();
  });

  it("renders nothing for an unpriced structure", () => {
    const { container } = render(
      <PayoffChart
        candidate={{
          ...QQQ,
          pricing: { kind: "unpriced", reason: "no NBBO for the short leg" },
        }}
      />,
    );
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing when a bound is unbounded", () => {
    const { container } = render(
      <PayoffChart
        candidate={{
          ...QQQ,
          pricing: { ...QQQ.pricing, maxLoss: null } as CandidateView["pricing"],
        }}
      />,
    );
    // An invented ceiling would draw a bound the position does not have.
    expect(container.innerHTML).toBe("");
  });

  it("renders nothing without a spot or a breakeven", () => {
    const { container } = render(
      <PayoffChart candidate={{ ...QQQ, spot: undefined }} />,
    );
    expect(container.innerHTML).toBe("");
  });
});

describe("GammaBars", () => {
  /** QQQ's recorded dealer-gamma rows for 2026-09-03. */
  const LEVELS = [
    { strike: 710, label: "Call Wall", role: "resistance", value: 13785 },
    { strike: 710, label: "Put Wall", role: "support", value: 13785 },
    { strike: 665, label: "Gamma Flip", role: "flip", value: 0 },
    { strike: 660, label: "Accel ↑", role: "accelerator", value: 0 },
  ];

  it("collapses a duplicate (strike, label) row, first occurrence winning", () => {
    render(
      <GammaBars
        ticker="QQQ"
        spot="717.43"
        levels={[...LEVELS, { ...LEVELS[0], value: -1 }]}
      />,
    );
    expect(screen.getAllByText("710.00").length).toBe(2); // Call Wall + Put Wall
    expect(screen.getAllByText("+13,785").length).toBe(2);
  });

  it("prints a bare 0 in muted text where gamma is zero", () => {
    const { container } = render(
      <GammaBars ticker="QQQ" spot="717.43" levels={LEVELS} />,
    );
    expect(screen.getAllByText("0").length).toBe(2);
    // The zero rows draw a stub on the axis, not a bar.
    expect(container.querySelectorAll("rect[width='2']").length).toBe(2);
  });

  it("carries a caption that says which side is which", () => {
    render(<GammaBars ticker="QQQ" spot="717.43" levels={LEVELS} />);
    expect(
      screen.getByText("− short gamma · 0 · long gamma +"),
    ).toBeTruthy();
  });

  it("renders nothing with no levels", () => {
    const { container } = render(
      <GammaBars ticker="QQQ" spot="717.43" levels={[]} />,
    );
    expect(container.innerHTML).toBe("");
  });
});
