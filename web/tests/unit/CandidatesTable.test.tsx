/* @vitest-environment jsdom */
import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";

import { CandidatesTable } from "@/components/vrp/CandidatesTable";

describe("CandidatesTable", () => {
  it("renders a candidate row with the four strikes", () => {
    render(
      <CandidatesTable
        candidates={[
          {
            ticker: "NVDA",
            as_of: "2026-06-22",
            structure: "iron_condor",
            spot: "120",
            iv: "0.45",
            vrp_z: "1.8",
            hold_days: 20,
            short_put: "110",
            long_put: "104",
            short_call: "130",
            long_call: "136",
            entry_credit: "1.8",
            max_loss: "4.2",
            bucket_sector: "Semis",
            bucket_verdict: "HARVEST_SELLABLE",
            earnings_clear: true,
            contracts: 1,
          },
        ]}
      />,
    );
    // getByText throws if absent → calling it is the presence assertion
    expect(screen.getByText("NVDA")).toBeDefined();
    expect(screen.getByText("110.0")).toBeDefined(); // short put
    expect(screen.getByText(/HARVEST_SELLABLE/)).toBeDefined();
  });

  it("shows an empty-state message when there are no candidates", () => {
    render(<CandidatesTable candidates={[]} />);
    expect(screen.getByText(/No iron-condor candidates/i)).toBeDefined();
  });
});
