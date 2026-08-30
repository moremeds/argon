import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import {
  EnergyDisciplinePanel,
  EnergyInventoryPanel,
  EnergyProposedPanels,
  EnergyRoutePanel,
} from "@/components/macro/domain/EnergyProposal";

/**
 * Board tab 06 — Energy · Proposal.
 *
 * The tab ships with no data path at all, which makes exactly two things worth testing:
 * that its one panel carrying numbers cannot be mistaken for a live reading, and that no
 * panel on it invents a value or a label.
 */
describe("energy data inventory", () => {
  it("carries its measurement date and says the counts are a citation", () => {
    // These counts were true on the day the enumeration ran and nothing re-checks them.
    // Elsewhere on this desk a stale number is a bug; here the date IS the number's
    // meaning, so it has to be on the page rather than implied by it.
    render(<EnergyInventoryPanel />);
    const panel = screen.getByTestId("board-panel-energy-inventory");
    expect(panel.textContent).toContain("2026-08-26");
    expect(panel.textContent).toContain("not a live check");
    expect(panel.getAttribute("data-basis")).toBe("REFERENCE");
    expect(screen.getByTestId("energy-inventory-read").textContent).toContain(
      "not a live market reading",
    );
  });

  it("names the shape of the finding, not just its rows", () => {
    render(<EnergyInventoryPanel />);
    const rows = screen.getAllByRole("row");
    // header + five enumerated sources.
    expect(rows).toHaveLength(6);
    expect(screen.getByText("0 energy series")).toBeTruthy();
    expect(screen.getAllByText("already collecting")).toHaveLength(2);
  });
});

describe("the proposal's own boundaries", () => {
  it("keeps the route PLANNED and renders previews as non-panel ghosts", () => {
    // A PLANNED panel that rendered a number would be the one failure the basis
    // vocabulary exists to prevent: a description of intent wearing the clothes of a
    // measurement.
    render(
      <>
        <EnergyRoutePanel />
        <EnergyProposedPanels />
      </>,
    );
    expect(
      screen.getByTestId("board-panel-energy-route").getAttribute("data-basis"),
    ).toBe("PLANNED");
    expect(screen.queryByTestId("board-panel-energy-proposed")).toBeNull();
    expect(screen.getAllByTestId("energy-proposed-ghost")).toHaveLength(3);
  });

  it("refuses a fifth domain state until one is measured", () => {
    // The whole argument of the tab. Four labels existing is not a reason for a fifth;
    // a spec and a threshold measurement are, exactly as the four existing domains had.
    render(<EnergyDisciplinePanel />);
    const note = screen.getByTestId("energy-discipline");
    expect(note.textContent).toContain("HONEST BOUNDARY");
    expect(note.textContent).toContain("No energy state until thresholds are measured");
  });
});
