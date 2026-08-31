import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ChainCalendar } from "@/components/fundamentals/ChainCalendar";
import { DeltaRail } from "@/components/fundamentals/DeltaRail";
import { CaseCards } from "@/components/fundamentals/CaseCards";
import { CaseStageTables } from "@/components/fundamentals/CaseStageTables";
import { DeskLimits } from "@/components/fundamentals/DeskLimits";
import { DeskMasthead } from "@/components/fundamentals/DeskMasthead";
import { ScopeTable } from "@/components/fundamentals/ScopeTable";
import {
  chainPoints,
  summariseCase,
  valuationMarks,
} from "@/lib/fundamentals/desk";
import type {
  CaseStage,
  CaseStageMember,
  ChainMetricCell,
  DeltaRailResponse,
  DeskCalendarResponse,
  DeskCalendarRow,
  DeskCapexResponse,
  DeskCase,
  DeskLimitsResponse,
  DeskMatrixResponse,
  MemberDot,
  ScopeGroup,
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
    layer: "L3",
    layer_rank: 0,
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

// --- Level-1 spine fixtures -------------------------------------------------
//
// AUTHORING STEP (run once, 2026-08-29, against `option_wizard_local` THROUGH
// THE REAL REPORT FUNCTIONS — `spine.desk_capex` / `spine.desk_cases` — not
// hand-written).
//
// CAPEX is the real response's last six quarters, verbatim, in dollars.
// CASES/optical is the FULL real optical chain — every stage, every member,
// every filed figure — so its stage medians reproduce production exactly
// (Upstream +72.5%, Switch +34.1%, Modules +48.8%, Systems +30.6%,
// Customer +17.8%). CASES/datacenter is a deliberate SUBSET of the real chain
// (2 of the real 6-14 members per stage, all real names at their real filed
// figures): its medians are the subset's own and are NOT production's, so the
// assertions below compute what they expect from the fixture rather than
// quoting a production number the subset does not carry.
//
// COHR and CEG really do have a null gross margin in the store; POET really
// grew +266% (the off-scale branch); ACM really has a negative gross margin;
// JNPR really has no rollup row. Every null and every flag below is a real
// property of a real filing, not a constructed shape.

const CAPEX: DeskCapexResponse = {
  chain: "Cloud/Hyperscaler",
  included: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
  // BABA is a real member of the real chain and really does file in CNY.
  excluded: { BABA: "CNY" },
  quarters: [
    {
      quarter: "2025Q1",
      capex_usd: 65218000000,
      revenue_usd: 344638000000,
      tickers: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
      complete: true,
    },
    {
      quarter: "2025Q2",
      capex_usd: 80998000000,
      revenue_usd: 373451000000,
      tickers: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
      complete: true,
    },
    {
      quarter: "2025Q3",
      capex_usd: 87199000000,
      revenue_usd: 391445000000,
      tickers: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
      complete: true,
    },
    {
      quarter: "2025Q4",
      capex_usd: 109664000000,
      revenue_usd: 444233000000,
      tickers: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
      complete: true,
    },
    {
      quarter: "2026Q1",
      capex_usd: 129779000000,
      revenue_usd: 407408000000,
      tickers: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
      complete: true,
    },
    {
      quarter: "2026Q2",
      capex_usd: 151656000000,
      revenue_usd: 446755000000,
      tickers: ["AMZN", "GOOGL", "IBM", "MSFT", "ORCL"],
      complete: true,
    },
  ],
};

function member(
  ticker: string,
  rev: number | null,
  gm: number | null,
  over: Partial<CaseStageMember> = {},
): CaseStageMember {
  return {
    ticker,
    rev_yoy: rev,
    gross_margin: gm,
    spot_percentile: null,
    reported_currency: null,
    ...over,
  };
}

function stage(
  layer: string,
  rank: number,
  chain: string,
  members: CaseStageMember[],
): CaseStage {
  const mid = (xs: number[]) =>
    xs.length === 0
      ? null
      : xs.length % 2
        ? xs[(xs.length - 1) / 2]
        : (xs[xs.length / 2 - 1] + xs[xs.length / 2]) / 2;
  const yoys = members
    .map((m) => m.rev_yoy)
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b);
  const gms = members
    .map((m) => m.gross_margin)
    .filter((v): v is number => v !== null)
    .sort((a, b) => a - b);
  return {
    layer,
    chain,
    rank,
    members,
    median_rev_yoy: mid(yoys),
    median_gross_margin: mid(gms),
    reporting: yoys.length,
    total: members.length,
  };
}

const OPT = "Optical-Communication";

// Stages arrive rank-ASCENDING from the API — upstream first. A fixture
// already ordered customer-first could not prove the funnel reverses it.
const CASES: DeskCase[] = [
  {
    domain: "dc_buildout",
    slug: "datacenter",
    label: "Datacenter buildout",
    stages: [
      stage("EPC-Construction", 10, "EPC/Construction", [
        member("ACM", -0.04238, -0.009493),
        member("DY", 0.297598, 0.140007),
      ]),
      stage("Generation", 20, "Generation/Nuclear", [
        member("CEG", 0.284638, null),
        member("VST", -0.283954, 0.23525),
      ]),
      stage("Power-Electrical", 30, "Power/Electrical", [
        member("ETN", 0.155252, 0.334662),
        member("VRT", 0.262327, 0.377149),
      ]),
      stage("Cooling-Thermal", 40, "Cooling/Thermal", [
        member("CARR", -0.015804, 0.272083),
        member("TT", 0.070351, 0.355662),
      ]),
      stage("DC-REIT-Colo", 50, "DC-REIT/Colo", [
        member("DLR", 0.187414, 0.08423),
        member("EQIX", 0.098848, 0.531429),
      ]),
    ],
  },
  {
    domain: "optical_communication",
    slug: "optical",
    label: "Optical interconnect",
    stages: [
      stage("Upstream-Components", 10, OPT, [
        member("AAOI", 0.618459, 0.277232),
        member("COHR", 0.225187, null),
        member("LITE", 0.832219, 0.474312),
        member("POET", 2.660572, -0.801909),
      ]),
      stage("Semi-DSP-Switch", 20, OPT, [
        member("AVGO", 0.32288, 0.672421),
        member("CRDO", 2.056759, 0.682071),
        member("MRVL", 0.340742, 0.521466),
      ]),
      stage("Module-Transceiver", 30, OPT, [
        member("AAOI", 0.618459, 0.277232),
        member("COHR", 0.225187, null),
        member("FN", 0.357313, 0.122702),
        member("LITE", 0.832219, 0.474312),
      ]),
      stage("Systems-Networking", 40, OPT, [
        member("ANET", 0.325731, 0.629278),
        member("CIEN", 0.305915, 0.440273),
        // JNPR has no rollup row at all. It stays IN the stage and out of the
        // median — the branch that must never render as a zero.
        member("JNPR", null, null),
        member("NTAP", 0.053713, 0.700719),
      ]),
      stage("Customer-Cloud", 70, OPT, [
        member("AMZN", 0.157666, 0.522557),
        member("GOOGL", 0.200507, 0.61649),
        member("META", 0.276526, 0.813654),
        member("MSFT", 0.177887, 0.67197),
        member("ORCL", 0.173505, 0.651845),
      ]),
    ],
  },
];

// Real, from the active taxonomy: groups outside the AI/semi domains.
const SCOPE: ScopeGroup[] = [
  { chain: "Sector-ETF", domains: ["unclassified"], members: 18 },
  { chain: "Consumer", domains: ["unclassified"], members: 8 },
  { chain: "M7", domains: ["unclassified"], members: 8 },
  { chain: "Crypto", domains: ["unclassified"], members: 6 },
];

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
  // Real filers and their real reporting currencies, frozen: TSM and UMC
  // file in TWD, which is the measurement that banned cross-name dollar sums.
  non_usd_filers: [
    { ticker: "TSM", currencies: ["TWD"] },
    { ticker: "UMC", currencies: ["TWD"] },
  ],
};

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
    expect(
      within(cohr).getByTestId("first-known-at").textContent ?? "",
    ).toContain("2026-08-26");
    expect(within(cohr).getByTestId("occurred-at").textContent ?? "").toContain(
      "2026-06-30",
    );
  });

  it("names the collapsed sibling class rather than hiding it", () => {
    render(<DeltaRail data={RAIL_ASCENDING} />);
    const cohr = screen.getByTestId("delta-event-COHR");
    expect(within(cohr).getByTestId("delta-also").textContent ?? "").toContain(
      "statement_published",
    );
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
    expect(
      within(cohr).getByTestId("implied-move").textContent ?? "",
    ).toContain("8.1%");
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
    expect(
      within(aaoi).getByTestId("percentile-state").textContent ?? "",
    ).toContain("no_coverage");
    // And the covered row does NOT render a state in place of its phrase.
    const cohr = screen.getByTestId("desk-calendar-row-COHR");
    expect(within(cohr).queryByTestId("percentile-state")).toBeNull();
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
    expect(
      screen.getByTestId("withheld-composite").textContent ?? "",
    ).toContain(LIMITS.withheld_composite);
  });

  it("renders membership evidence as counts per class", () => {
    render(<DeskLimits data={LIMITS} />);
    const ev = screen.getByTestId("membership-evidence");
    expect(
      within(ev).getByTestId("evidence-disclosed").textContent ?? "",
    ).toContain("4");
    expect(
      within(ev).getByTestId("evidence-inferred").textContent ?? "",
    ).toContain("297");
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

// --- Chain-map / valuation reshaping (pure) ---------------------------------

describe("chainPoints", () => {
  it("keeps only chains that sit on a taxonomy PLANE", () => {
    // A positive layer_rank means the chain is a ranked stage of a modelled
    // flow — the funnels draw it, and placing it on a plane it does not sit
    // on would put a case chain in the middle of the map.
    const points = chainPoints([
      ...MATRIX.cells,
      cell({
        chain: "Optical-Communication",
        layer: "Upstream-Components",
        layer_rank: 10,
        metric: "rev_yoy",
        median: 0.725339,
      }),
      cell({
        chain: "Optical-Communication",
        layer: "Upstream-Components",
        layer_rank: 10,
      }),
    ]);
    expect(points.map((p) => p.chain)).not.toContain("Optical-Communication");
  });

  it("drops a chain with no median on either axis rather than placing it at the origin", () => {
    // The origin is "average growth, average margin". Putting "we hold
    // nothing for this" there is a claim, not an abstention.
    const points = chainPoints(MATRIX.cells);
    expect(points.map((p) => p.chain)).not.toContain("Semi-Logic/ASIC");
  });
});

describe("valuationMarks", () => {
  it("counts a name once even when it sits in two chains", () => {
    // chain_membership is (chain, layer, ticker)-grained. Counted naively the
    // numerator can exceed its own denominator.
    const twice = [
      ...MATRIX.cells,
      cell({
        chain: "Semi-Logic/ASIC",
        metric: "valuation_percentile",
        median: null,
        dots: [dot({ ticker: "COHR", value: 0.81 })],
      }),
    ];
    const { marks, universe } = valuationMarks(twice);
    expect(marks.filter((m) => m.ticker === "COHR")).toHaveLength(1);
    expect(marks.length).toBeLessThanOrEqual(universe);
  });

  it("counts a name with no band in the universe but not in the marks", () => {
    const { marks, universe } = valuationMarks([
      cell({
        metric: "valuation_percentile",
        median: null,
        dots: [
          dot({ ticker: "COHR", value: 0.81 }),
          dot({ ticker: "POET", value: null, state: "no_coverage" }),
        ],
      }),
    ]);
    // Coverage is the honest headline: 1 of 2, never 1 of 1.
    expect(marks).toHaveLength(1);
    expect(universe).toBe(2);
  });
});

describe("summariseCase", () => {
  it("reads the customer as the HIGHEST rank, not the first row", () => {
    // Customer-Cloud is rank 70 and arrives LAST from the API. Read the other
    // way, every funnel is upside down and every ratio inverts.
    const optical = summariseCase(CASES[1].stages)!;
    expect(optical.customer.layer).toBe("Customer-Cloud");
    expect(optical.upstream.layer).toBe("Upstream-Components");
  });

  it("computes amplification as upstream over customer", () => {
    const optical = summariseCase(CASES[1].stages)!;
    const expected =
      (optical.upstream.median_rev_yoy as number) /
      (optical.customer.median_rev_yoy as number);
    expect(optical.amplification).toBeCloseTo(expected, 10);
    // The measured optical reading, reproduced from the full real chain.
    expect(optical.amplification).toBeCloseTo(4.078, 2);
  });

  it("refuses a ratio when the customer median is not positive", () => {
    // Dividing through zero or a negative denominator is arithmetic, not
    // amplification, and it would print a confident number for nonsense.
    const flat = summariseCase([
      stage("Upstream-Components", 10, OPT, [member("AAOI", 0.6, 0.2)]),
      stage("Customer-Cloud", 70, OPT, [member("AMZN", -0.1, 0.5)]),
    ])!;
    expect(flat.amplification).toBeNull();
  });

  it("counts a dual-listed company once, and says how many there are", () => {
    // AAOI, COHR and LITE really sit in BOTH Upstream-Components and
    // Module-Transceiver.
    const optical = summariseCase(CASES[1].stages)!;
    expect(optical.memberships).toBeGreaterThan(optical.distinctCompanies);
    expect(optical.dualListed).toBe(
      optical.memberships - optical.distinctCompanies,
    );
  });
});

// --- CaseCards --------------------------------------------------------------

describe("CaseCards", () => {
  it("shows both cases and the amplification each one carries", () => {
    render(<CaseCards cases={CASES} />);
    const cards = screen.getByTestId("case-cards");
    const text = cards.textContent ?? "";
    expect(text).toContain("Optical interconnect");
    expect(text).toContain("Datacenter buildout");
    expect(text).toContain("4.08");
  });

  it("says how many supplying stages sit BELOW their own customer", () => {
    // The finding that no sector screen can produce: proximity to the AI
    // dollar does not guarantee participation in it.
    render(<CaseCards cases={CASES} />);
    const dc = summariseCase(CASES[0].stages)!;
    const cm = dc.customer.median_rev_yoy as number;
    const below = dc.downstreamFirst
      .slice(1)
      .filter((s) => (s.median_rev_yoy as number) < cm);
    expect(below.length).toBeGreaterThan(0);
    expect(screen.getByTestId("case-cards").textContent ?? "").toContain(
      `${below.length} of the ${dc.downstreamFirst.length - 1} supplying stages`,
    );
  });
});

// --- Claims that must FOLLOW the data ---------------------------------------
//
// Every finding on this desk is written as a sentence, and a sentence outlives
// the numbers it was written against. These fixtures deliberately falsify the
// condition each sentence asserts and check the sentence retreats. A test that
// only pins today's wording would pass forever while the desk went on claiming
// something the data had stopped supporting.

describe("DeskMasthead", () => {
  /** The value rendered next to a stamp label, read from the cell itself.
   *  Asserting on the whole masthead is not a test: its prose already
   *  contains an em-dash, so a `toContain("—")` passes whatever the cell says. */
  const stamp = (label: string) =>
    screen.getByText(label).nextElementSibling?.textContent ?? "";

  it("prints a dash, never a zero, for a count whose request failed", () => {
    // "0 chains modelled" is a claim the desk made about the world. A failed
    // matrix request entitles it to no claim at all, and printing zero would
    // put that claim beside a panel simultaneously reporting an API error.
    render(
      <DeskMasthead
        chains={null}
        companies={null}
        capexQuarters={null}
        layers={null}
      />,
    );
    expect(stamp("chains modelled")).toBe("—");
    expect(stamp("companies")).toBe("—");
    expect(stamp("quarters of capex")).toBe("—");
  });

  it("prints a real zero when the desk genuinely holds nothing", () => {
    // The other half: a dash must not swallow a true empty answer either.
    render(<DeskMasthead chains={0} companies={0} capexQuarters={0} layers={0} />);
    expect(stamp("chains modelled")).toBe("0");
  });
});

describe("prose retreats when its condition stops holding", () => {
  /** Same shape as CASES, but every supplying stage OUTGROWS its customer. */
  const NO_LAG: DeskCase[] = [
    {
      domain: "optical_communication",
      slug: "optical",
      label: "Optical interconnect",
      stages: [
        stage("Upstream-Components", 10, OPT, [member("AVGO", 0.6, 0.7)]),
        stage("Module-Transceiver", 30, OPT, [member("COHR", 0.5, 0.4)]),
        stage("Customer-Cloud", 70, OPT, [member("MSFT", 0.1, 0.7)]),
      ],
    },
    {
      domain: "dc_buildout",
      slug: "datacenter",
      label: "Datacenter buildout",
      stages: [
        stage("Power-Electrical", 20, "Power/Electrical", [
          member("ETN", 0.3, 0.38),
        ]),
        stage("DC-REIT-Colo", 50, "DC-REIT/Colo", [member("EQIX", 0.1, 0.5)]),
      ],
    },
  ];

  it("drops the 'slower than the customers it supplies' clause when none is", () => {
    // The word is an assertion; the number beside it would stay correct while
    // the word went false. Nothing on screen would show the difference.
    render(<CaseCards cases={NO_LAG} />);
    const text = screen.getByTestId("case-cards").textContent ?? "";
    expect(text).not.toContain("slower than the customers it supplies");
    expect(text).not.toMatch(/\b0 of the \d+ supplying stages/);
  });

  it("still prints both amplifications when no stage lags", () => {
    // Retreating from a claim must not take the measurement with it.
    render(<CaseCards cases={NO_LAG} />);
    expect(screen.getByTestId("case-cards").textContent ?? "").toContain(
      "6.00",
    );
  });

  it("stops calling the cases 'completely different' when they converge", () => {
    const CLOSE: DeskCase[] = [
      NO_LAG[0],
      {
        ...NO_LAG[1],
        stages: [
          stage("Power-Electrical", 20, "Power/Electrical", [
            member("ETN", 0.55, 0.38),
          ]),
          stage("DC-REIT-Colo", 50, "DC-REIT/Colo", [member("EQIX", 0.1, 0.5)]),
        ],
      },
    ];
    render(<CaseCards cases={CLOSE} />);
    const text = screen.getByTestId("case-cards").textContent ?? "";
    expect(text).toContain("measurably different rates");
    expect(text).not.toContain("completely differently");
  });

  it("keeps 'completely differently' while the gap is real", () => {
    render(<CaseCards cases={CASES} />);
    expect(screen.getByTestId("case-cards").textContent ?? "").toContain(
      "completely differently",
    );
  });
});

// --- CaseStageTables --------------------------------------------------------

describe("CaseStageTables", () => {
  it("names a company with no filed quarter instead of dropping or zeroing it", () => {
    render(<CaseStageTables cases={CASES} />);
    const tables = screen.getByTestId("case-stage-tables");
    expect(within(tables).getAllByText("JNPR").length).toBeGreaterThan(0);
    expect(tables.textContent ?? "").toContain("no filed quarter");
    // The load-bearing half: it must not have been rendered as +0.0%.
    const row = within(tables).getAllByText("JNPR")[0].closest("tr");
    expect(row?.textContent ?? "").not.toMatch(/\+0\.0%/);
  });

  it("prints each stage median WITH its coverage, never alone", () => {
    render(<CaseStageTables cases={CASES} />);
    // Systems-Networking is 3 of 4 reporting because JNPR abstains.
    expect(screen.getByTestId("case-stage-tables").textContent ?? "").toContain(
      "3/4 reported",
    );
  });

  it("flags a name past the funnel's radius cap rather than letting it set the scale", () => {
    render(<CaseStageTables cases={CASES} />);
    const tables = screen.getByTestId("case-stage-tables");
    // POET really grew +266%, well past the 80% cap.
    const row = within(tables).getAllByText("POET")[0].closest("tr");
    expect(row?.textContent ?? "").toContain("off scale");
  });

  it("flags a negative gross margin", () => {
    render(<CaseStageTables cases={CASES} />);
    const row = within(screen.getByTestId("case-stage-tables"))
      .getAllByText("ACM")[0]
      .closest("tr");
    expect(row?.textContent ?? "").toContain("negative GM");
  });
});

// --- ScopeTable -------------------------------------------------------------

describe("ScopeTable", () => {
  it("names each out-of-scope group under its OWN name", () => {
    // Never "unclassified": these are the desk's own organising tags for
    // names held for reasons unrelated to this chain.
    render(<ScopeTable groups={SCOPE} />);
    const scope = screen.getByTestId("desk-scope");
    expect(scope.textContent ?? "").toContain("Sector-ETF");
    expect(scope.textContent ?? "").toContain("Consumer");
    expect(scope.textContent ?? "").not.toMatch(/unclassified/i);
  });

  it("separates a portfolio tag from a different industry", () => {
    render(<ScopeTable groups={SCOPE} />);
    const scope = screen.getByTestId("desk-scope");
    const rows = within(scope).getAllByRole("row");
    const tag = rows.find((r) => r.textContent?.includes("Sector-ETF"));
    const industry = rows.find((r) => r.textContent?.includes("Consumer"));
    expect(tag?.textContent ?? "").toContain("no stages to order");
    expect(industry?.textContent ?? "").toContain("A different industry");
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
const deskLimits = vi.fn();
const deskCapex = vi.fn();
const deskScope = vi.fn();
const deskCases = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      deskDelta: (...a: unknown[]) => deskDelta(...a),
      deskCalendar: (...a: unknown[]) => deskCalendar(...a),
      deskMatrix: (...a: unknown[]) => deskMatrix(...a),
      deskLimits: (...a: unknown[]) => deskLimits(...a),
      deskCapex: (...a: unknown[]) => deskCapex(...a),
      deskScope: (...a: unknown[]) => deskScope(...a),
      deskCases: (...a: unknown[]) => deskCases(...a),
    },
  };
});

// The three canvas panels are stubbed here for the same reason the repo
// already stubs lightweight-charts components: jsdom has no 2D context, so
// `getContext("2d")` returns null and a scene that needs one throws inside
// the effect. Their drawing is covered by a Playwright spec instead; what
// these page tests are for is the FETCH-TO-PROP wiring around them.
vi.mock("@/components/fundamentals/CapexPanel", () => ({
  CapexPanel: () => <div data-testid="capex-panel-stub" />,
}));
vi.mock("@/components/fundamentals/ChainMapPanel", () => ({
  ChainMapPanel: () => <div data-testid="chain-map-stub" />,
}));
vi.mock("@/components/fundamentals/ValuationPanel", () => ({
  ValuationPanel: () => <div data-testid="valuation-stub" />,
}));

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
    deskLimits.mockResolvedValue(LIMITS);
    deskCapex.mockResolvedValue(CAPEX);
    deskScope.mockResolvedValue(SCOPE);
    deskCases.mockResolvedValue(CASES);
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

  it("lets one panel fail without taking the rest of the ladder down", async () => {
    deskDelta.mockRejectedValue(new Error("API 500 for /delta: boom"));
    await renderDesk();
    expect(
      within(screen.getByTestId("delta-rail")).getByRole("alert"),
    ).not.toBeNull();
    // The desk's job is to show which halves it holds. A page-wide rejection
    // would replace a partial answer with no answer.
    expect(screen.getByTestId("chain-map-stub")).not.toBeNull();
    expect(screen.getByTestId("ni-basis")).not.toBeNull();
    expect(screen.getByTestId("desk-scope")).not.toBeNull();
  });

  it("surfaces a failed capex request rather than a flat capex line", async () => {
    // Question one is the desk's premise. An empty capex panel would read as
    // "the spending stopped", which is a claim about the world made out of a
    // request failure.
    deskCapex.mockRejectedValue(new Error("API 500 for /capex: boom"));
    await renderDesk();
    const section = screen.getByTestId("desk-capex");
    expect(within(section).getByRole("alert").textContent ?? "").toContain(
      "500",
    );
    expect(within(section).queryByTestId("capex-panel-stub")).toBeNull();
  });

  it("surfaces a failed limits request rather than an empty limits panel", async () => {
    deskLimits.mockRejectedValue(new Error("API 500 for /limits: boom"));
    await renderDesk();
    const section = screen.getByTestId("desk-limits-section");
    expect(within(section).getByRole("alert").textContent ?? "").toContain(
      "500",
    );
    expect(within(section).queryByTestId("ni-basis")).toBeNull();
  });

  it("surfaces a failed scope request rather than an empty boundary", async () => {
    // An empty boundary table says "this desk covers everything in the
    // taxonomy" — the opposite of what the section exists to say.
    deskScope.mockRejectedValue(new Error("API 500 for /scope: boom"));
    await renderDesk();
    const section = screen.getByTestId("desk-boundary");
    expect(within(section).getByRole("alert")).not.toBeNull();
    expect(within(section).queryByTestId("desk-scope")).toBeNull();
  });

  it("raises notFound when the section itself is not registered", async () => {
    // Task 13 answers 404 for an unknown section, which `allow404` turns into
    // null. An empty desk would claim the section exists and nothing is
    // happening in it — false in both clauses.
    deskCalendar.mockResolvedValue(null);
    const { default: DeskPage } =
      await import("@/app/fundamentals/ai-semi/page");
    await expect(DeskPage()).rejects.toThrow("NEXT_NOT_FOUND");
  });
});

// --- The cases page ---------------------------------------------------------

vi.mock("@/components/fundamentals/CaseFunnels", () => ({
  CaseFunnels: () => <div data-testid="case-funnels-stub" />,
}));

describe("the cases page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    deskCases.mockResolvedValue(CASES);
  });

  it("renders both cases from ONE request, so they share one scale", async () => {
    const { default: CasesPage } =
      await import("@/app/fundamentals/ai-semi/cases/page");
    render(await CasesPage());
    expect(deskCases).toHaveBeenCalledTimes(1);
    const cards = screen.getByTestId("case-cards");
    expect(cards.textContent ?? "").toContain("Optical interconnect");
    expect(cards.textContent ?? "").toContain("Datacenter buildout");
  });

  it("surfaces a failed cases request rather than an empty flow", async () => {
    deskCases.mockRejectedValue(new Error("API 500 for /cases: boom"));
    const { default: CasesPage } =
      await import("@/app/fundamentals/ai-semi/cases/page");
    render(await CasesPage());
    expect(screen.getByRole("alert").textContent ?? "").toContain("500");
    expect(screen.queryByTestId("case-cards")).toBeNull();
  });
});
