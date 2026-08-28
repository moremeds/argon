import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { CapexContextStrip } from "@/components/fundamentals/CapexContextStrip";
import { ChainCalendar } from "@/components/fundamentals/ChainCalendar";
import { ChainMetricMatrix } from "@/components/fundamentals/ChainMetricMatrix";
import { DeltaRail } from "@/components/fundamentals/DeltaRail";
import { DeskLimits } from "@/components/fundamentals/DeskLimits";
import { ProfitPoolStrip } from "@/components/fundamentals/ProfitPoolStrip";
import type {
  ChainMetricCell,
  DeltaRailResponse,
  DeskCalendarResponse,
  DeskCalendarRow,
  DeskLimitsResponse,
  DeskMatrixResponse,
  MemberDot,
  ProfitPoolLayer,
} from "@/lib/api";

// --- Fixtures ---------------------------------------------------------------
//
// AUTHORING STEP (run once, 2026-08-28, against `option_wizard_local`):
//
//   SELECT ticker, period_end, (raw_jsonb->>'total_revenue')::numeric,
//          (raw_jsonb->>'gross_profit')::numeric
//     FROM uw_scan.fundamental_statement_obs
//    WHERE statement='income' AND ticker IN ('COHR','LITE','CIEN','APH','AAOI')
//
// gross_margin = gross_profit / total_revenue; rev_yoy = rev / rev[-4q] - 1.
// The five figures below are those real filed values, frozen with their fiscal
// period. The tests never touch the network or the database.
//
//   APH  2026-06-30  gm 0.405111  yoy 0.550024
//   CIEN 2026-04-30  gm 0.440273  yoy 0.395124
//   COHR 2026-06-30  gm 0.384747  yoy 0.293492
//   LITE 2026-06-30  gm 0.474312  yoy 1.093405
//   AAOI 2026-06-30  gm 0.277236  yoy 0.864202
//
// CALENDAR dates/sessions and the DELTA RAIL's two clocks are constructed
// SHAPES and labelled as such: migrations 144-146 are not applied to
// `option_wizard_local`, so `earnings_calendar` and `research_events` hold
// nothing there to freeze. The tickers and chain names are real; the dates
// exercise render branches and claim nothing about what these names print.
//
// EVERY fixture carries rows on BOTH sides of every boundary a test asserts.
// A "not covered" assertion over a fixture with no null implied move cannot
// fail, and that is the failure mode this branch keeps re-finding.

function dot(over: Partial<MemberDot> = {}): MemberDot {
  return {
    ticker: "COHR",
    value: 0.384747,
    state: "ok",
    knowledge_date_estimated: false,
    ...over,
  };
}

const GROSS_MARGIN_DOTS: MemberDot[] = [
  dot({ ticker: "COHR", value: 0.384747 }),
  dot({ ticker: "APH", value: 0.405111 }),
  dot({ ticker: "CIEN", value: 0.440273 }),
  dot({ ticker: "LITE", value: 0.474312 }),
];

// The true unweighted median of the four dots above: (0.405111 + 0.440273) / 2.
const GROSS_MARGIN_MEDIAN = 0.422692;

function cell(over: Partial<ChainMetricCell>): ChainMetricCell {
  return {
    chain: "Networking/Optical",
    metric: "gross_margin",
    median: GROSS_MARGIN_MEDIAN,
    dots: GROSS_MARGIN_DOTS,
    cohorts: [
      { as_of: "2026-08-16", label: "reported", tickers: ["COHR", "APH"] },
    ],
    coverage_missing: [],
    members_total: 4,
    ...over,
  };
}

const MATRIX: DeskMatrixResponse = {
  section: "ai-semi",
  chains: ["Networking/Optical", "Semi-Logic/ASIC"],
  cells: [
    // A metric that DOES carry a median — the discriminating counterpart to
    // the valuation cell below.
    cell({}),
    // Own-history percentiles: dots only, median null by contract.
    cell({
      metric: "valuation_percentile",
      median: null,
      dots: [
        dot({ ticker: "COHR", value: 0.81, knowledge_date_estimated: null }),
        dot({ ticker: "LITE", value: 0.34, knowledge_date_estimated: null }),
      ],
    }),
    // Members straddle two as_of buckets: reporting season.
    cell({
      chain: "Semi-Logic/ASIC",
      metric: "rev_yoy",
      median: 0.550024,
      dots: [
        dot({ ticker: "APH", value: 0.550024 }),
        dot({ ticker: "AAOI", value: 0.864202 }),
      ],
      // THREE cohorts, two of them `awaiting`. `label` is 'reported' for the
      // newest bucket and 'awaiting' for every older one, so this is the shape
      // reporting season actually produces — a fixture holding one of each
      // cannot catch a key or testid that collides on the label.
      cohorts: [
        { as_of: "2026-08-16", label: "reported", tickers: ["APH"] },
        { as_of: "2026-05-17", label: "awaiting", tickers: ["AAOI"] },
        { as_of: "2026-02-15", label: "awaiting", tickers: ["MRVL"] },
      ],
    }),
    // Every member abstains: no value anywhere, so no median exists.
    cell({
      chain: "Semi-Logic/ASIC",
      metric: "gross_margin",
      median: null,
      dots: [
        dot({ ticker: "MRVL", value: null, state: "no_compatible_run" }),
        dot({ ticker: "AVGO", value: null, state: "no_coverage" }),
      ],
      coverage_missing: ["MRVL", "AVGO"],
      members_total: 2,
    }),
  ],
};

function calRow(over: Partial<DeskCalendarRow>): DeskCalendarRow {
  return {
    ticker: "COHR",
    report_date: "2026-09-03",
    session: "afterhours",
    chain: "Networking/Optical",
    layer: "L3",
    layer_rank: 3,
    implied_move_pct: 0.081,
    implied_move_asof: "2026-08-27",
    reactions: [-0.0177, 0.0412],
    spot_percentile: 0.8,
    percentile_state: "ok",
    ...over,
  };
}

// Deliberately NOT in date order: the response's order is the desk's reading
// order (upstream -> downstream), and the component must not "helpfully" sort
// it into a chronology. A fixture already sorted by date could not tell the
// difference.
const CALENDAR: DeskCalendarResponse = {
  section: "ai-semi",
  as_of: "2026-08-28",
  rows: [
    calRow({ ticker: "COHR", report_date: "2026-09-03", layer_rank: 3 }),
    calRow({
      ticker: "AAOI",
      report_date: "2026-08-31", // EARLIER than the row above it
      layer_rank: 4,
      implied_move_pct: null,
      implied_move_asof: null,
      spot_percentile: null,
      percentile_state: "no_coverage",
    }),
  ],
};

const RAIL_ASCENDING: DeltaRailResponse = {
  since: "2026-08-21",
  // Ascending on purpose. The rail's contract is `first_known_at` DESC, and a
  // fixture that already arrives DESC cannot prove the component enforces it.
  events: [
    {
      event_class: "statement_published",
      ticker: "AAOI",
      occurred_at: "2026-06-30",
      first_known_at: "2026-08-22",
      title: "AAOI filed its June quarter",
      detail: {},
    },
    {
      event_class: "sec_filing",
      ticker: "COHR",
      occurred_at: "2026-06-30",
      first_known_at: "2026-08-26",
      title: "COHR 10-Q indexed at SEC",
      detail: { also: "statement_published" },
    },
  ],
};

const LIMITS: DeskLimitsResponse = {
  ni_basis_agree: 311,
  ni_basis_differ: 42,
  ni_largest_basis_differences: ["VZ", "T", "GE"],
  ni_sign_flip_violations: 5,
  withheld_composite:
    "No composite is published at chain grain. The composite orders names " +
    "cross-sectionally and cannot time one name against itself.",
  membership_evidence: [
    { evidence_class: "disclosed", memberships: 4 },
    { evidence_class: "inferred", memberships: 297 },
  ],
  exposure_coverage: [
    {
      chain: "Networking/Optical",
      members: 16,
      with_exposure: 6,
      with_magnitude: 2,
    },
  ],
};

const PROFIT_POOL: ProfitPoolLayer[] = [
  // Out of rank order on purpose.
  {
    chain: "Networking/Optical",
    layer_rank: 3,
    median_gross_margin: GROSS_MARGIN_MEDIAN,
    median_rev_yoy: 0.395124,
    dots: GROSS_MARGIN_DOTS,
  },
  {
    chain: "Semi-Logic/ASIC",
    layer_rank: 1,
    median_gross_margin: null,
    median_rev_yoy: null,
    dots: [dot({ ticker: "MRVL", value: null, state: "no_coverage" })],
  },
];

// --- DeltaRail --------------------------------------------------------------

describe("DeltaRail", () => {
  it("orders by first_known_at DESC even when the response arrives ascending", () => {
    render(<DeltaRail data={RAIL_ASCENDING} />);
    const rows = screen.getAllByTestId(/^delta-event-/);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "delta-event-COHR", // first_known_at 2026-08-26
      "delta-event-AAOI", // first_known_at 2026-08-22
    ]);
  });

  it("shows both clocks on every event, including when they differ", () => {
    render(<DeltaRail data={RAIL_ASCENDING} />);
    const cohr = screen.getByTestId("delta-event-COHR");
    // The knowledge clock is the rail's ordering key and must be visible as
    // such; the world clock is a different date and must not be substituted
    // for it. COHR learned-on 2026-08-26 about a 2026-06-30 quarter.
    expect(within(cohr).getByTestId("first-known-at").textContent ?? "").toContain("2026-08-26");
    expect(within(cohr).getByTestId("occurred-at").textContent ?? "").toContain("2026-06-30");
  });

  it("names the collapsed sibling class rather than hiding it", () => {
    render(<DeltaRail data={RAIL_ASCENDING} />);
    const cohr = screen.getByTestId("delta-event-COHR");
    expect(within(cohr).getByTestId("delta-also").textContent ?? "").toContain("statement_published");
    // The AAOI event collapsed nothing, so it carries no `also` marker — the
    // discriminating half.
    const aaoi = screen.getByTestId("delta-event-AAOI");
    expect(within(aaoi).queryByTestId("delta-also")).toBeNull();
  });

  it("renders an empty rail as a statement, not a blank", () => {
    render(<DeltaRail data={{ since: "2026-08-21", events: [] }} />);
    expect(screen.getByTestId("delta-rail-empty")).not.toBeNull();
  });
});

// --- ChainCalendar ----------------------------------------------------------

describe("ChainCalendar", () => {
  it("renders rows in the response's order and never re-sorts by date", () => {
    render(<ChainCalendar data={CALENDAR} />);
    const rows = screen.getAllByTestId(/^desk-calendar-row-/);
    expect(rows.map((r) => r.getAttribute("data-testid"))).toEqual([
      "desk-calendar-row-COHR", // prints 2026-09-03
      "desk-calendar-row-AAOI", // prints 2026-08-31, EARLIER, and stays second
    ]);
  });

  it("names an uncovered implied move instead of drawing a zero", () => {
    render(<ChainCalendar data={CALENDAR} />);
    const aaoi = screen.getByTestId("desk-calendar-row-AAOI");
    expect(within(aaoi).getByTestId("implied-move-not-covered")).not.toBeNull();
    // Discriminating counterpart: the covered row shows the figure.
    const cohr = screen.getByTestId("desk-calendar-row-COHR");
    expect(within(cohr).getByTestId("implied-move").textContent ?? "").toContain("8.1%");
  });

  it("lets a percentile reach the screen only as a phrase that says which way is cheap", () => {
    render(<ChainCalendar data={CALENDAR} />);
    const cohr = screen.getByTestId("desk-calendar-row-COHR");
    const phrase = within(cohr).getByTestId("own-history-phrase");
    // 0.80 is a YIELD percentile: high means CHEAP. A bare "0.80" in a column
    // of prices reads as the opposite, which is why the number never ships
    // without the direction attached to it.
    expect(phrase.textContent ?? "").toMatch(/cheaper than 80%/i);
  });

  it("renders the percentile's state when there is no percentile", () => {
    render(<ChainCalendar data={CALENDAR} />);
    const aaoi = screen.getByTestId("desk-calendar-row-AAOI");
    expect(within(aaoi).getByTestId("percentile-state").textContent ?? "").toContain("no_coverage");
    // And the covered row does NOT render a state in place of its phrase.
    const cohr = screen.getByTestId("desk-calendar-row-COHR");
    expect(within(cohr).queryByTestId("percentile-state")).toBeNull();
  });
});

// --- ChainMetricMatrix ------------------------------------------------------

describe("ChainMetricMatrix", () => {
  it("renders a median and the per-name dots for a metric that has one", () => {
    render(<ChainMetricMatrix data={MATRIX} />);
    const c = screen.getByTestId("matrix-cell-Networking/Optical-gross_margin");
    expect(within(c).getByTestId("cell-median").textContent ?? "").toContain("42.3%");
    expect(within(c).getAllByTestId(/^cell-dot-/)).toHaveLength(4);
  });

  it("renders own-history percentiles as dots with NO median", () => {
    render(<ChainMetricMatrix data={MATRIX} />);
    const v = screen.getByTestId(
      "matrix-cell-Networking/Optical-valuation_percentile",
    );
    // A median over own-history percentiles would be a claim about the chain
    // that nothing measured.
    expect(within(v).queryByTestId("cell-median")).toBeNull();
    expect(within(v).getAllByTestId(/^cell-dot-/)).toHaveLength(2);
    expect(
      within(v).getByTestId("cell-name-level-caption"),
    ).not.toBeNull();
  });

  it("splits straddling members into two labeled cohorts and merges no median across them", () => {
    render(<ChainMetricMatrix data={MATRIX} />);
    const c = screen.getByTestId("matrix-cell-Semi-Logic/ASIC-rev_yoy");
    const reported = within(c).getByTestId("cohort-reported-2026-08-16");
    const awaiting = within(c).getByTestId("cohort-awaiting-2026-05-17");
    expect(reported.textContent ?? "").toContain("APH");
    expect(awaiting.textContent ?? "").toContain("AAOI");
    // BOTH older buckets render as their own group. Merging them, or keying
    // them on the shared label, loses one cross-section entirely.
    expect(within(c).getAllByTestId(/^cohort-awaiting-/)).toHaveLength(2);
    expect(
      within(c).getByTestId("cohort-awaiting-2026-02-15").textContent ?? "",
    ).toContain("MRVL");
    // The median belongs to the dominant cohort and is displayed under it —
    // never floating above both, where it would read as their average.
    expect(within(reported).getByTestId("cell-median").textContent ?? "").toContain("55.0%");
    expect(within(awaiting).queryByTestId("cell-median")).toBeNull();
  });

  it("states which abstention an empty cell is in, never blank", () => {
    render(<ChainMetricMatrix data={MATRIX} />);
    const e = screen.getByTestId("matrix-cell-Semi-Logic/ASIC-gross_margin");
    const abst = within(e).getByTestId("cell-abstention");
    expect(abst.textContent ?? "").toContain("no_compatible_run");
    expect(abst.textContent ?? "").toContain("no_coverage");
    // "the job never ran" and "this company has no fundamentals" are different
    // claims and must not collapse into one another.
    expect(abst.textContent).not.toBe("");
  });

  it("names the missing tickers rather than a bare count", () => {
    render(<ChainMetricMatrix data={MATRIX} />);
    const e = screen.getByTestId("matrix-cell-Semi-Logic/ASIC-gross_margin");
    const missing = within(e).getByTestId("cell-coverage-missing");
    expect(missing.textContent ?? "").toContain("MRVL");
    expect(missing.textContent ?? "").toContain("AVGO");
    // A cell with full coverage renders no missing list at all.
    const full = screen.getByTestId(
      "matrix-cell-Networking/Optical-gross_margin",
    );
    expect(within(full).queryByTestId("cell-coverage-missing")).toBeNull();
  });
});

// --- ProfitPoolStrip --------------------------------------------------------

describe("ProfitPoolStrip", () => {
  it("orders layers by layer_rank", () => {
    render(<ProfitPoolStrip layers={PROFIT_POOL} />);
    const cols = screen.getAllByTestId(/^profit-pool-layer-/);
    expect(cols.map((c) => c.getAttribute("data-testid"))).toEqual([
      "profit-pool-layer-1",
      "profit-pool-layer-3",
    ]);
  });

  it("abstains rather than printing a zero margin", () => {
    render(<ProfitPoolStrip layers={PROFIT_POOL} />);
    const l1 = screen.getByTestId("profit-pool-layer-1");
    expect(within(l1).getByTestId("layer-margin-absent")).not.toBeNull();
    const l3 = screen.getByTestId("profit-pool-layer-3");
    expect(within(l3).getByTestId("layer-margin").textContent ?? "").toContain("42.3%");
  });

  it("carries no arrow, no lead, and no lag anywhere in its output", () => {
    const { container } = render(<ProfitPoolStrip layers={PROFIT_POOL} />);
    // Positive anchor FIRST: if the strip rendered nothing, the three absence
    // assertions below would pass vacuously and pin nothing at all.
    expect(screen.getAllByTestId(/^profit-pool-layer-/)).toHaveLength(2);
    const text = container.textContent ?? "";
    expect(text).not.toContain("→");
    expect(text).not.toMatch(/\bleads?\b/i);
    expect(text).not.toMatch(/\blags?\b/i);
  });
});

// --- CapexContextStrip ------------------------------------------------------

describe("CapexContextStrip", () => {
  it("states the sign inversion that makes capex context rather than edge", () => {
    render(<CapexContextStrip />);
    const strip = screen.getByTestId("capex-context");
    expect(strip.textContent ?? "").toMatch(/cost line, not demand/i);
    expect(strip.textContent ?? "").toMatch(/context, not edge/i);
  });

  it("points at the filed figures instead of restating a number it does not hold", () => {
    render(<CapexContextStrip />);
    const links = within(screen.getByTestId("capex-context")).getAllByRole(
      "link",
    );
    // The spenders, by name — the strip states whose capex it is talking about
    // rather than gesturing at "hyperscalers" and holding no figure at all.
    expect(links.map((l) => l.textContent)).toEqual([
      "MSFT",
      "AMZN",
      "GOOGL",
      "META",
    ]);
    for (const l of links) {
      expect(l.getAttribute("href")).toContain("/stock/");
    }
  });
});

// --- DeskLimits -------------------------------------------------------------

describe("DeskLimits", () => {
  it("renders the NI basis split with its named largest gaps", () => {
    render(<DeskLimits data={LIMITS} />);
    const basis = screen.getByTestId("ni-basis");
    expect(basis.textContent ?? "").toContain("311");
    expect(basis.textContent ?? "").toContain("42");
    expect(basis.textContent ?? "").toContain("VZ");
  });

  it("never labels the basis difference a failure", () => {
    render(<DeskLimits data={LIMITS} />);
    const basis = screen.getByTestId("ni-basis");
    // Anchor first, so the four absence assertions cannot pass on an empty
    // region: a difference here is usually correct accounting on BOTH sides
    // (ASC 230 consolidated-incl-NCI vs attributable-to-parent), and argon
    // stores no NCI field to attribute it with.
    expect(basis.textContent ?? "").toMatch(/ASC 230/);
    const text = basis.textContent ?? "";
    expect(text).not.toMatch(/\bfail(ed|ure|s)?\b/i);
    expect(text).not.toMatch(/\boffender/i);
    expect(text).not.toMatch(/\berror/i);
    expect(text).not.toMatch(/\bviolation/i);
  });

  it("does label the sign flip a violation, because that one is", () => {
    render(<DeskLimits data={LIMITS} />);
    const flips = screen.getByTestId("ni-sign-flips");
    expect(flips.textContent ?? "").toContain("5");
    expect(flips.textContent ?? "").toMatch(/violation/i);
  });

  it("renders the withheld-composite sentence verbatim", () => {
    render(<DeskLimits data={LIMITS} />);
    expect(screen.getByTestId("withheld-composite").textContent ?? "").toContain(LIMITS.withheld_composite);
  });

  it("renders membership evidence as counts per class", () => {
    render(<DeskLimits data={LIMITS} />);
    const ev = screen.getByTestId("membership-evidence");
    expect(within(ev).getByTestId("evidence-disclosed").textContent ?? "").toContain("4");
    expect(within(ev).getByTestId("evidence-inferred").textContent ?? "").toContain("297");
  });

  it("renders all three exposure denominators, not just the first", () => {
    render(<DeskLimits data={LIMITS} />);
    const row = screen.getByTestId("exposure-Networking/Optical");
    // 16 members / 6 with an exposure row / 2 with a disclosed magnitude —
    // showing only the first invites the reader to assume the third.
    expect(row.textContent ?? "").toContain("16");
    expect(row.textContent ?? "").toContain("6");
    expect(row.textContent ?? "").toContain("2");
  });
});

// --- The page ---------------------------------------------------------------
//
// These four exist because of what the node page's review found one layer
// down: every error test there injected an `error` prop straight into a
// component, so nothing pinned that the PAGE ever hands one over. With the
// prop dropped, `?? []` turned a failed request into "no upcoming print is
// held" — a coverage claim manufactured out of a failure. The fetchers below
// therefore REJECT, through the real page component.

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

const deskDelta = vi.fn();
const deskCalendar = vi.fn();
const deskMatrix = vi.fn();
const deskProfitPool = vi.fn();
const deskLimits = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      deskDelta: (...a: unknown[]) => deskDelta(...a),
      deskCalendar: (...a: unknown[]) => deskCalendar(...a),
      deskMatrix: (...a: unknown[]) => deskMatrix(...a),
      deskProfitPool: (...a: unknown[]) => deskProfitPool(...a),
      deskLimits: (...a: unknown[]) => deskLimits(...a),
    },
  };
});

async function renderDesk() {
  const { default: DeskPage } = await import("@/app/fundamentals/ai-semi/page");
  return render(await DeskPage());
}

describe("the ai-semi desk page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    deskDelta.mockResolvedValue(RAIL_ASCENDING);
    deskCalendar.mockResolvedValue(CALENDAR);
    deskMatrix.mockResolvedValue(MATRIX);
    deskProfitPool.mockResolvedValue(PROFIT_POOL);
    deskLimits.mockResolvedValue(LIMITS);
  });

  it("never turns a failed calendar request into a coverage claim", async () => {
    deskCalendar.mockRejectedValue(new Error("API 500 for /calendar: boom"));
    await renderDesk();
    // The error has to reach the screen...
    const cal = screen.getByTestId("desk-calendar");
    expect(within(cal).getByRole("alert").textContent ?? "").toContain("500");
    // ...and, the load-bearing half, the affirmative sentence must be GONE.
    // An error banner rendered above a lying empty state is still a lying
    // empty state.
    expect(within(cal).queryByTestId("desk-calendar-empty")).toBeNull();
  });

  it("lets one panel fail without taking the other five down", async () => {
    deskDelta.mockRejectedValue(new Error("API 500 for /delta: boom"));
    await renderDesk();
    expect(
      within(screen.getByTestId("delta-rail")).getByRole("alert"),
    ).not.toBeNull();
    // The desk's job is to show which halves it holds. A page-wide rejection
    // would replace a partial answer with no answer.
    expect(
      screen.getByTestId("matrix-cell-Networking/Optical-gross_margin"),
    ).not.toBeNull();
    expect(screen.getByTestId("ni-basis")).not.toBeNull();
  });

  it("surfaces a failed limits request rather than an empty limits panel", async () => {
    deskLimits.mockRejectedValue(new Error("API 500 for /limits: boom"));
    await renderDesk();
    const limits = screen.getByTestId("desk-limits");
    expect(within(limits).getByRole("alert").textContent ?? "").toContain("500");
    expect(within(limits).queryByTestId("ni-basis")).toBeNull();
  });

  it("raises notFound when the section itself is not registered", async () => {
    // Task 13 answers 404 for an unknown section, which `allow404` turns into
    // null. An empty desk would claim the section exists and nothing is
    // happening in it — false in both clauses.
    deskCalendar.mockResolvedValue(null);
    const { default: DeskPage } = await import("@/app/fundamentals/ai-semi/page");
    await expect(DeskPage()).rejects.toThrow("NEXT_NOT_FOUND");
  });
});
