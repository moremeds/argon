import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { RatesDesk } from "@/components/rates/RatesDesk";
import { SNAPSHOT, TENORS } from "./fixture";

describe("RatesDesk", () => {
  it("renders all reference-page anchors and KPI tiles", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    for (const label of [
      "Summary",
      "Curve",
      "Decomp",
      "Scorecard",
      "Policy",
      "Supply",
      "Positioning",
      "Cross",
      "Events",
      "Sources",
      "Synthesis",
    ]) {
      expect(screen.getByRole("link", { name: label })).toBeTruthy();
    }

    for (const label of ["2Y", "5Y", "10Y", "30Y", "2s10s", "5s30s"]) {
      expect(screen.getAllByText(label).length).toBeGreaterThan(0);
    }
  });

  it("renders the full eleven-tenor curve table", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    for (const tenor of TENORS) {
      expect(screen.getByRole("row", { name: new RegExp(`^${tenor}\\b`) })).toBeTruthy();
    }
  });

  it("marks not-yet-wired source panels unavailable instead of filling static values", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getAllByText("Unavailable").length).toBeGreaterThan(0);
    expect(screen.getByText(/Treasury auction feed not wired/)).toBeTruthy();
    expect(screen.getByText(/CFTC\/TIC feeds not wired/)).toBeTruthy();
  });

  it("renders source freshness so failed refreshes do not look live", () => {
    render(<RatesDesk snapshot={SNAPSHOT} />);

    expect(screen.getByText("10Y Treasury")).toBeTruthy();
    expect(screen.getByText("Stale")).toBeTruthy();
  });

  it("renders an explicit empty state when no snapshot exists", () => {
    render(<RatesDesk snapshot={null} />);

    expect(screen.getByText(/Rates snapshot not computed/)).toBeTruthy();
  });
});
