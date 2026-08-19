import { render, screen } from "@testing-library/react";
import { describe, expect, it } from "vitest";
import ValueSubTab from "@/components/scanner/value/ValueSubTab";
import type { components } from "@/lib/types";

type Candidate = components["schemas"]["ValueCandidate"];

// Real rows from uw_scan.valuation_anchors at as_of 2026-08-17, engine
// fundamentals-v1:77aea364. BAX crossed into its zone between 08-14 and 08-17;
// BRO was already in and carries the HIGHEST percentile here; AAON got its
// first band that day and therefore has nothing to have crossed.
const BAX: Candidate = {
  ticker: "BAX",
  company_type: "unclassified",
  method: "sales_to_ev",
  spot: "25.91",
  buy_below: "26.5389800492436",
  observe_mid: "39.6686490583759",
  risk_above: "51.9278503121108",
  spot_percentile: 0.8,
  history_quarters: 20,
  confidence: "medium",
  confidence_reasons: ["no sector on file for this name"],
  entered: true,
  as_of: "2026-08-17",
};

const BRO: Candidate = {
  ...BAX,
  ticker: "BRO",
  spot: "68.86",
  buy_below: "89.0239946849381",
  spot_percentile: 1,
  entered: false,
};

const AAON: Candidate = {
  ...BAX,
  ticker: "AAON",
  spot: "88.09",
  buy_below: "121.070172484609",
  spot_percentile: 1,
  entered: null,
};

const response = (candidates: Candidate[]) => ({
  candidates,
  engine_version: "fundamentals-v1:77aea364",
  as_of: "2026-08-17",
  banded_universe: 336,
  generated_at: "2026-08-17T23:10:00Z",
});

describe("ValueSubTab", () => {
  it("badges NEW only for a name that actually crossed", () => {
    render(<ValueSubTab value={response([BAX, AAON, BRO])} />);
    const rows = screen.getAllByRole("row").slice(1); // drop the header
    expect(rows[0].textContent).toContain("BAX");
    expect(rows[0].textContent).toContain("NEW");
    // `entered: null` is UNKNOWN. Reading it as NEW would have badged 29 names
    // on 2026-08-17 that were there because the panel widened.
    expect(rows[1].textContent).toContain("AAON");
    expect(rows[1].textContent).not.toContain("NEW");
    expect(rows[1].textContent).toContain("first band");
    expect(rows[2].textContent).not.toContain("NEW");
    expect(rows[2].textContent).not.toContain("first band");
  });

  it("never prints the raw yield percentile as a number", () => {
    render(<ValueSubTab value={response([BAX])} />);
    // 0.80 means CHEAP, and printed bare it reads as a price rank the wrong way
    // round. Only the phrase may reach the screen.
    expect(screen.queryByText("0.8")).toBeNull();
    expect(screen.queryByText("0.80")).toBeNull();
    expect(
      screen.getByText("Cheaper than 16 of its last 20 quarters"),
    ).toBeTruthy();
  });

  it("states on screen that the list is unranked", () => {
    render(<ValueSubTab value={response([BAX, BRO])} />);
    // BRO is the cheapest row against its own history and renders last. The
    // caption is what stops a reader inferring an ordering from that anyway.
    expect(screen.getByText(/unranked/)).toBeTruthy();
    expect(screen.getByText(/its own past/)).toBeTruthy();
  });

  it("reports depth against each name's own buy_below", () => {
    render(<ValueSubTab value={response([BAX, BRO])} />);
    // (26.5389800492436 - 25.91) / 26.5389800492436 = 2.368%
    expect(screen.getByText("2.4%")).toBeTruthy();
    // (89.0239946849381 - 68.86) / 89.0239946849381 = 22.65%, one decimal
    expect(screen.getByText("22.7%")).toBeTruthy();
  });

  it("says the stack is down rather than showing an empty buy zone", () => {
    render(<ValueSubTab value={undefined} />);
    expect(
      screen.getByText(/no active fundamental method version/),
    ).toBeTruthy();
    expect(screen.queryByRole("table")).toBeNull();
  });
});
