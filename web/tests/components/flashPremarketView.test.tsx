import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { PremarketView } from "@/components/flash/PremarketView";
import type { BriefView } from "@/components/flash/view";
import { PREMARKET_VIEW } from "../fixtures/flashRun";

const FOOTER =
  "All structures are defined-risk. No quantities, position sizes or account information appear anywhere in this flash.";

describe("PremarketView", () => {
  it("leads with the run's one sentence and closes with the defined-risk line", () => {
    const { container } = render(<PremarketView view={PREMARKET_VIEW} />);
    expect(screen.getByText(/Real yields did the work/)).toBeTruthy();
    expect(container.textContent).toContain(FOOTER);
  });

  it("renders the decision rows in the reviewer's order", () => {
    render(<PremarketView view={PREMARKET_VIEW} />);
    const keys = screen
      .getAllByTestId("decision-key")
      .map((el) => el.textContent);
    expect(keys).toEqual(["Call", "Action", "Confidence"]);
  });

  it("says nothing was flagged rather than dropping the overnight panel", () => {
    render(<PremarketView view={{ ...PREMARKET_VIEW, overnight: [] }} />);
    expect(screen.getByText("Overnight")).toBeTruthy();
    expect(screen.getByText("Nothing was flagged overnight.")).toBeTruthy();
  });

  it("prints the policy source verbatim and never says CME FedWatch", () => {
    const { container } = render(<PremarketView view={PREMARKET_VIEW} />);
    expect(container.textContent).toContain("not CME FedWatch");
    expect(container.textContent).not.toMatch(/via CME FedWatch/);
  });

  it("shows the degradation band only when the run recorded one", () => {
    const { container } = render(<PremarketView view={PREMARKET_VIEW} />);
    expect(container.textContent).not.toContain("Run degraded");

    const degraded: BriefView = {
      ...PREMARKET_VIEW,
      degradation: ["tool unconfigured: ow_ib_positions (OW_IB_API_BASE unset)"],
    };
    const degradedRender = render(<PremarketView view={degraded} />);
    expect(
      within(degradedRender.container).getByText(
        /tool unconfigured: ow_ib_positions/,
      ),
    ).toBeTruthy();
  });

  it("renders an empty run's own line and no decision block", () => {
    const empty: BriefView = {
      schemaVersion: 1,
      date: "2026-09-03",
      empty: true,
    };
    const { container } = render(<PremarketView view={empty} />);
    expect(screen.getByText(/recorded no content/i)).toBeTruthy();
    expect(container.querySelectorAll('[data-testid="decision-key"]')).toHaveLength(
      0,
    );
  });
});
