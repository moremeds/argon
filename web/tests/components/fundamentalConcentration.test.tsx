import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import { FundamentalConcentration } from "@/components/stock/panels/FundamentalConcentration";
import type { components } from "@/lib/types";

type Concentration = components["schemas"]["FundamentalConcentrationResponse"];

// NVDA's real concentration, derived from the frozen 2026-08-18 UW breakdown
// fixture the Python tests read. The trend is the tail of the real 19-point
// series; every figure here came out of `build_card`, none was composed.
const NVDA: Concentration = {
  ticker: "NVDA",
  segment: {
    axis: "us-gaap:StatementBusinessSegmentsAxis",
    level: "all",
    n_members: 2,
    top_member: "nvda:ComputeAndNetworkingSegmentMember",
    top_share: 0.9134,
    report_date: "2026-04-26",
  },
  geography: {
    axis: "srt:StatementGeographicalAxis",
    level: "all",
    n_members: 4,
    top_member: "country:US",
    top_share: 0.7813,
    report_date: "2026-04-26",
  },
  trend: [
    {
      report_date: "2025-04-27",
      segment_top_share: 0.8985,
      geography_top_share: 0.4707,
    },
    {
      report_date: "2025-07-27",
      segment_top_share: 0.8842,
      geography_top_share: 0.5021,
    },
    {
      report_date: "2025-10-26",
      segment_top_share: 0.893,
      geography_top_share: 0.6872,
    },
    {
      report_date: "2026-04-26",
      segment_top_share: 0.9134,
      geography_top_share: 0.7813,
    },
  ],
  dropped_annual_periods: [
    "2021-01-31",
    "2022-01-30",
    "2023-01-29",
    "2024-01-28",
    "2025-01-26",
    "2026-01-25",
  ],
  derivation_version: "concentration-v1",
};

const card = (over: Partial<Concentration> = {}): Concentration => ({
  ...NVDA,
  ...over,
});

describe("FundamentalConcentration", () => {
  it("renders both families at their real shares", () => {
    render(<FundamentalConcentration c={card()} />);
    expect(screen.getByText("91.3%")).toBeTruthy();
    expect(screen.getByText("78.1%")).toBeTruthy();
  });

  it("renders the member string exactly as filed", () => {
    // Not "Compute & Networking", not a US flag. Filers mix `country:US` with
    // custom members and continent aggregates; prettifying means inventing a
    // taxonomy the filer did not use.
    render(<FundamentalConcentration c={card()} />);
    expect(
      screen.getByText("nvda:ComputeAndNetworkingSegmentMember"),
    ).toBeTruthy();
    expect(screen.getByText("country:US")).toBeTruthy();
  });

  it("renders an absent family as na and never as a zero share", () => {
    const { container } = render(
      <FundamentalConcentration c={card({ geography: null })} />,
    );
    expect(screen.getByText("na")).toBeTruthy();
    // "0.0%" would read as "no geographic concentration" — a claim about the
    // company rather than about our coverage.
    expect(container.textContent).not.toContain("0.0%");
  });

  it("names the excluded annual periods instead of hiding them", () => {
    const { container } = render(<FundamentalConcentration c={card()} />);
    expect(container.textContent).toContain("6 annual periods excluded");
    for (const period of NVDA.dropped_annual_periods) {
      expect(container.textContent).toContain(period);
    }
  });

  it("says nothing when no period was dropped", () => {
    const { container } = render(
      <FundamentalConcentration c={card({ dropped_annual_periods: [] })} />,
    );
    expect(container.textContent).not.toContain("excluded from the");
  });

  it("declares itself descriptive and carries the derivation version", () => {
    // The block sits beside seven scored tiles. Without this it reads as an
    // eighth score, which D2 explicitly forbids.
    const { container } = render(<FundamentalConcentration c={card()} />);
    expect(container.textContent).toContain("descriptive");
    expect(container.textContent).toContain("not scored");
    expect(container.textContent).toContain("concentration-v1");
  });
});
