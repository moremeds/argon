import { render, screen, within } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { DesignNotes } from "@/components/macro/DesignNotes";

describe("DesignNotes", () => {
  it("states the four data bases and their distinct meanings", () => {
    render(<DesignNotes />);

    const panel = screen.getByTestId("board-panel-method-basis");
    for (const label of ["Live", "Derived", "Planned", "Reference"]) {
      expect(within(panel).getAllByText(label).length).toBeGreaterThan(0);
    }
    expect(panel.getAttribute("data-basis")).toBe("REFERENCE");
  });

  it("documents every analytical page and its replay clock", () => {
    render(<DesignNotes />);

    const table = screen.getByTestId("macro-binding-table");
    for (const page of [
      "Overview",
      "Fed",
      "Rates",
      "Inflation",
      "Dollar",
      "Gold",
      "Energy",
      "Factors",
    ]) {
      expect(within(table).getByText(page)).toBeTruthy();
    }
    expect(within(table).getByText("Observation date")).toBeTruthy();
  });

  it("keeps implementation review prose out of the product surface", () => {
    const { container } = render(<DesignNotes />);
    expect(container.textContent).not.toContain("Deep-review verdict");
    expect(container.textContent).not.toContain("Vercel monitors");
  });
});
