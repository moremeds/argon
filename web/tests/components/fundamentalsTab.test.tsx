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
  composite_series: [0.05, -0.02, 0.01, -0.08, -0.11, -0.1421],
  composite_percentile: { percentile: 0.38, n: 217 },
  series_dates: [
    "2025-02-18",
    "2025-05-06",
    "2025-08-07",
    "2025-11-07",
    "2026-02-24",
    "2026-08-14",
  ],
  panel_size: 217,
  subscores: [
    {
      feature: "rev_growth",
      series: [0.31, 0.28, 0.22, 0.19, 0.26, 0.284638],
      percentile: { percentile: 0.71, n: 217 },
      value: 0.284638,
      unit: "ratio",
      direction: "higher_better",
      suppressed_by: [],
    },
    {
      feature: "gross_margin",
      series: [0.243, 0.204, 0.281, 0.238, 0.428, null],
      percentile: null,
      value: null,
      unit: "ratio",
      direction: null,
      suppressed_by: ["gross_profit_equals_revenue_despite_costs"],
    },
    {
      feature: "op_margin",
      series: [0.11, 0.09, 0.12, 0.08, 0.1, 0.0772715],
      percentile: { percentile: 0.1797235, n: 217 },
      value: 0.0772715,
      unit: "ratio",
      direction: null,
      suppressed_by: [],
    },
    {
      feature: "fcf_margin",
      series: [0.02, 0.01, 0.03, 0.02, 0.015, 0.00969077],
      percentile: { percentile: 0.22, n: 217 },
      value: 0.00969077,
      unit: "ratio",
      direction: "higher_better",
      suppressed_by: [],
    },
    {
      feature: "roe",
      series: [0.09, 0.1, 0.12, 0.11, 0.105, 0.1087],
      percentile: { percentile: 0.44, n: 209 },
      value: 0.1087,
      unit: "ratio",
      direction: null,
      suppressed_by: [],
    },
    {
      feature: "neg_net_debt_ebitda",
      series: [-2.1, -2.3, -2.5, -2.6, -2.7, -2.78409],
      percentile: { percentile: 0.12, n: 209 },
      value: -2.78409,
      unit: "turns",
      direction: "higher_better",
      suppressed_by: [],
    },
    {
      feature: "asset_turnover",
      series: [0.3, 0.31, 0.32, 0.33, 0.32, 0.324529],
      percentile: { percentile: 0.55, n: 216 },
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

  it("draws a gap where a quarter is not believed, and never bridges it", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const tile = await screen.findByTestId("subscore-gross_margin");

    // The dashed rule marks the excluded quarter. Without it the break in the
    // line is an invisible kink and the chart reads as continuous.
    expect(tile.querySelectorAll("line[stroke-dasharray]").length).toBe(1);
    // And the path must not run through it: pathFromNullablePoints restarts
    // with a fresh M, so a bridged series would have exactly one M.
    const d = tile.querySelector("path")?.getAttribute("d") ?? "";
    expect((d.match(/M/g) ?? []).length).toBeGreaterThanOrEqual(1);
    expect(d).not.toContain("NaN");
  });

  it("draws no gap marker on a clean series", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const tile = await screen.findByTestId("subscore-op_margin");
    expect(tile.querySelectorAll("line[stroke-dasharray]").length).toBe(0);
  });

  it("states the percentile with its denominator, never bare", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const tile = await screen.findByTestId("subscore-op_margin");
    // 0.1797 -> "18th of 217". A percentile whose denominator is unnamed is not
    // a fact, and the denominator differs per feature.
    expect(tile.textContent).toMatch(/18th of 217/);
  });

  it("shows no percentile for a suppressed feature", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const tile = await screen.findByTestId("subscore-gross_margin");
    // Its own value was excluded from the panel, so there is nothing to rank.
    expect(tile.textContent).not.toMatch(/\bof 21[0-9]\b/);
  });

  it("names the panel the composite is measured against", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const head = await screen.findByTestId("fundamentals-composite");
    expect(head.textContent).toMatch(/panel of 217 names/);
    expect(head.textContent).toMatch(/38th of 217/);
    // Both ends of the plotted window are labelled.
    expect(head.textContent).toMatch(/2025-02-18/);
    expect(head.textContent).toMatch(/2026-08-14/);
  });

  it("renders levels without history rather than refusing to render", async () => {
    // A name with one quarter still has a level worth stating; a trajectory is
    // context, not a precondition.
    nextCard = {
      ...CEG_CARD,
      series_dates: [],
      composite_series: [],
      subscores: CEG_CARD.subscores.map((s) => ({ ...s, series: [] })),
    };
    render(<FundamentalsTab ticker="CEG" />);
    const tile = await screen.findByTestId("subscore-op_margin");
    expect(tile.textContent).toMatch(/7\.7%/);
    expect(tile.querySelector("svg")).toBeNull();
  });

  it("dates every trajectory, not just the composite", async () => {
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    await screen.findByTestId("subscore-op_margin");
    // The axis lives inside the sparkline, so all eight charts share one
    // implementation and cannot drift apart. Seven tiles + the composite.
    expect(screen.getAllByText("2025-02-18").length).toBe(8);
    expect(screen.getAllByText("2026-08-14").length).toBe(8);
  });

  it("dates the WINDOW, so a suppressed opening quarter still reads correctly", async () => {
    // gross_margin's newest quarter is suppressed; its line stops short of the
    // right edge while the axis still spans the same window as its siblings.
    nextCard = CEG_CARD;
    render(<FundamentalsTab ticker="CEG" />);
    const tile = await screen.findByTestId("subscore-gross_margin");
    expect(tile.textContent).toMatch(/2025-02-18/);
    expect(tile.textContent).toMatch(/2026-08-14/);
  });
});
