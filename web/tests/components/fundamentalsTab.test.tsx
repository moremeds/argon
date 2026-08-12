import { render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

// A plain async function, deliberately not a `vi.fn()`: vitest's mock
// result-tracking attaches a handler to the returned promise without a rejection
// branch, so a `vi.fn()` returning `Promise.reject` is reported as an unhandled
// rejection even when the component catches it.
let nextCard: unknown = null;
let nextError: Error | null = null;
vi.mock("@/lib/api", () => ({
  api: {
    fundamentals: async () => {
      if (nextError) throw nextError;
      return nextCard;
    },
  },
}));

import { FundamentalsTab } from "@/components/stock/tabs/FundamentalsTab";

// CEG's real 2026-06-30 shape: UW echoes total_revenue into gross_profit while
// reporting a positive cost_of_revenue, so the derived gross margin is exactly
// 1.0 and must never reach the screen.
const CEG_CARD = {
  ticker: "CEG",
  composite: -0.1421,
  subscores: [
    {
      feature: "rev_growth",
      value: 0.284638,
      unit: "ratio",
      direction: "higher_better",
      suppressed_by: [],
    },
    {
      feature: "gross_margin",
      value: null,
      unit: "ratio",
      direction: null,
      suppressed_by: ["gross_profit_equals_revenue_despite_costs"],
    },
    {
      feature: "op_margin",
      value: 0.0772715,
      unit: "ratio",
      direction: null,
      suppressed_by: [],
    },
    {
      feature: "fcf_margin",
      value: 0.00969077,
      unit: "ratio",
      direction: "higher_better",
      suppressed_by: [],
    },
    {
      feature: "roe",
      value: 0.1087,
      unit: "ratio",
      direction: null,
      suppressed_by: [],
    },
    {
      feature: "neg_net_debt_ebitda",
      value: -2.78409,
      unit: "turns",
      direction: "higher_better",
      suppressed_by: [],
    },
    {
      feature: "asset_turnover",
      value: 0.324529,
      unit: "turns",
      direction: "higher_better",
      suppressed_by: [],
    },
  ],
  coverage: {
    features_present: 7,
    features_total: 7,
    missing: [],
    suppressed: ["gross_margin"],
  },
  provenance: {
    engine_version: "fundamentals-v1:77aea364",
    inputs_hash:
      "029d87486ad17570790f587f26246b1ad7eb1a141acd8a6000adab7c2b3f6059",
    as_of: "2026-08-14",
    period_end: "2026-06-30",
    knowledge_date: "2026-08-14",
    filing_date_known: false,
    source_obs_count: 3,
  },
};

describe("FundamentalsTab", () => {
  beforeEach(() => {
    nextCard = null;
    nextError = null;
  });

  it("never renders a suppressed figure, and says why", async () => {
    nextCard = CEG_CARD;
    const { container } = render(<FundamentalsTab ticker="CEG" />);

    const tile = await screen.findByTestId("subscore-gross_margin");
    expect(tile.textContent).toMatch(/na/);
    expect(tile.textContent).toMatch(
      /gross_profit_equals_revenue_despite_costs/,
    );
    // The bug this exists to prevent: a utility rendered at a 100% gross margin.
    expect(container.textContent).not.toMatch(/100\.0%/);
  });

  it("keeps sibling features that do not consume the flagged field", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    // op_margin is derived from operating_income, not gross_profit. Blanking the
    // whole income statement over one bad field would be as wrong as showing it.
    expect(
      (await screen.findByTestId("subscore-op_margin")).textContent,
    ).toMatch(/7\.7%/);
  });

  it("claims no direction for the features that measured inverted or untested", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    await screen.findByTestId("subscore-op_margin");
    // Two, not three: gross_margin also claims no direction, but it is
    // suppressed here and its tile shows the suppression reason instead. A
    // direction claim about a value we are refusing to show would be noise.
    expect(screen.getAllByText(/no direction claimed/i).length).toBe(2);
    expect(screen.getAllByText(/higher better/i).length).toBe(4);
  });

  it("separates 'not reported' from 'reported but not believed'", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const cov = await screen.findByTestId("fundamentals-coverage");
    expect(cov.textContent).toMatch(/Not reported: none/);
    expect(cov.textContent).toMatch(/Reported but not believed: Gross margin/);
  });

  it("dates the card by knowledge_date and flags the filing-date fallback", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const head = await screen.findByTestId("fundamentals-composite");
    expect(head.textContent).toMatch(/KNOWN 2026-08-14 \(EST\)/);
  });

  it("states the composite is not an expected return, with the space intact", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const head = await screen.findByTestId("fundamentals-composite");
    // JSX collapses the literal space adjacent to </strong>, which silently
    // rendered "notan expected return" until an explicit {" "} was added.
    expect(head.textContent).toMatch(/not an expected return/);
  });

  it("renders an empty state rather than an error when a name has no score", async () => {
    nextError = new Error("404");
    render(<FundamentalsTab ticker="ZZZZ" />);
    await waitFor(() =>
      expect(screen.getByTestId("fundamentals-empty").textContent).toMatch(
        /No fundamental score for ZZZZ/,
      ),
    );
  });
});
