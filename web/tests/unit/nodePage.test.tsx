import { render, screen, within } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { NodeAliasQuestions } from "@/components/fundamentals/NodeAliasQuestions";
import { NodeCalendarStrip } from "@/components/fundamentals/NodeCalendarStrip";
import { NodeLimits } from "@/components/fundamentals/NodeLimits";
import { NodeUnderwritingPanel } from "@/components/fundamentals/NodeUnderwritingPanel";
import type {
  DeskCalendarResponse,
  DeskCalendarRow,
  NodeUnderwritingRow,
  ReportResponse,
} from "@/lib/api";

// --- Fixtures ---------------------------------------------------------------
//
// UNDERWRITING rows are frozen from real filed values, pulled 2026-08-28 from
// `uw_scan.fundamental_statement_obs` on `option_wizard_local` for members of
// `Networking/Optical` (a real 16-name chain). DIO = inventory / cost_of_revenue
// x 91.25 and SBC/revenue = stock_based_compensation / total_revenue, computed
// from those same raw strings; the YoY uses each name's real four-quarters-back
// share count.
//
// CALENDAR rows are constructed SHAPES, and deliberately labelled as such:
// migrations 144-146 are not applied to `option_wizard_local`, so
// `uw_scan.earnings_calendar` does not exist there and there is nothing to
// freeze. The tickers and chain are real; the dates, sessions and moves exercise
// render branches and make no claim about what those names actually print.
//
// EVERY fixture carries rows on BOTH sides of every boundary a test asserts. A
// "not covered" assertion over a fixture with no null implied move cannot fail,
// and that is the failure mode this branch keeps hitting.

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
    reactions: [-0.0177, 0.0412, -0.0035, 0.1102],
    spot_percentile: null,
    percentile_state: "no_compatible_run",
    ...over,
  };
}

const CALENDAR: DeskCalendarResponse = {
  section: "ai-semi",
  as_of: "2026-08-28",
  rows: [
    // covered + classified session + reaction history
    calRow({ ticker: "COHR" }),
    // NOT covered by any implied-move snapshot
    calRow({
      ticker: "LITE",
      report_date: "2026-11-05",
      session: "premarket",
      implied_move_pct: null,
      implied_move_asof: null,
    }),
    // UW never classified the session (the permanent ~2%)
    calRow({
      ticker: "POET",
      report_date: "2026-09-11",
      session: null,
      implied_move_pct: 0.152,
      implied_move_asof: "2026-08-27",
    }),
    // no reaction history HELD -- not "the stock did not move"
    calRow({
      ticker: "ALAB",
      report_date: "2026-11-04",
      session: "afterhours",
      reactions: [],
    }),
  ],
};

const UNDERWRITING: NodeUnderwritingRow[] = [
  {
    ticker: "AAOI",
    period_end: "2026-06-30",
    dio: 183.39,
    sbc_to_revenue: 0.025338,
    shares_outstanding_yoy: 0.436766,
    filing_published_at: "2026-08-06",
    inventory_raw: "278791000",
    cost_of_revenue_raw: "138715000",
    sbc_raw: "4863000",
    shares_outstanding_raw: "81568000",
    state: "ok",
  },
  {
    ticker: "APH",
    period_end: "2026-06-30",
    dio: 79.72,
    sbc_to_revenue: 0.0051838,
    shares_outstanding_yoy: 0.0159155,
    filing_published_at: "2026-07-31",
    inventory_raw: "4551600000",
    cost_of_revenue_raw: "5210100000",
    sbc_raw: "45400000",
    shares_outstanding_raw: "1289400000",
    state: "ok",
  },
  {
    ticker: "CIEN",
    period_end: "2026-04-30",
    dio: 83.91,
    sbc_to_revenue: 0.035317,
    shares_outstanding_yoy: 0.0092569,
    filing_published_at: "2026-06-04",
    inventory_raw: "808447000",
    cost_of_revenue_raw: "879185000",
    sbc_raw: "55473000",
    shares_outstanding_raw: "146314000",
    state: "stale_run",
  },
  {
    ticker: "FN",
    period_end: "2026-06-30",
    dio: 80.73,
    sbc_to_revenue: 0.0062784,
    shares_outstanding_yoy: 0.0046558,
    filing_published_at: "2026-08-18",
    inventory_raw: "1021235000",
    cost_of_revenue_raw: "1154338000",
    sbc_raw: "8261000",
    shares_outstanding_raw: "36252000",
    state: "ok",
  },
  // Argon computed nothing compatible for this name. Distinct from the row
  // below it, which is a statement about what Argon HOLDS.
  {
    ticker: "CRDO",
    period_end: "2026-04-30",
    dio: null,
    sbc_to_revenue: null,
    shares_outstanding_yoy: null,
    filing_published_at: "2026-06-02",
    inventory_raw: null,
    cost_of_revenue_raw: null,
    sbc_raw: null,
    shares_outstanding_raw: null,
    state: "no_compatible_run",
  },
  {
    ticker: "EXTR",
    period_end: "2026-06-30",
    dio: null,
    sbc_to_revenue: null,
    shares_outstanding_yoy: null,
    filing_published_at: null,
    inventory_raw: null,
    cost_of_revenue_raw: null,
    sbc_raw: null,
    shares_outstanding_raw: null,
    state: "no_coverage",
  },
];

/** Same rows, every SBC stripped. Non-empty on purpose: the sentence must be a
 *  claim about filings that exist, not a vacuous truth over zero rows. */
const UNDERWRITING_NO_SBC: NodeUnderwritingRow[] = UNDERWRITING.map((r) => ({
  ...r,
  sbc_to_revenue: null,
  sbc_raw: null,
}));

function reportOk(): ReportResponse {
  return {
    state: "ok",
    versions: [
      {
        version_no: 1,
        created_at: "2026-08-27T00:00:00Z",
        status: "published",
      },
    ],
    delta: {
      is_first_version: true,
      manifest: [],
      added: [],
      removed: [],
      moved: [],
      summary: "first version",
    },
    report: {
      report_id: 1,
      report_key: "chain:Networking/Optical",
      report_type: "chain",
      version_no: 1,
      title: "Networking/Optical",
      content_hash: "a".repeat(64),
      status: "published",
      created_at: "2026-08-27T00:00:00Z",
      manifest: {
        engine_version: "fundamentals-v2",
        taxonomy_version: "taxonomy-v1",
        evidence_policy: "exclude",
        as_of: "2026-08-27",
        assembler_version: "chain/1",
        scope: { chain: "Networking/Optical" },
      },
      blocks: [
        {
          ordinal: 5,
          block_kind: "chain_exposure",
          title: "Disclosed economic exposure",
          payload: {
            exposures: [
              {
                ticker: "APH",
                role: "supplier",
                magnitude: 0.615,
                basis: "communicationssolutions alias",
                status: "disclosed",
                is_member: false,
                source_ref: null,
              },
              {
                ticker: "CIEN",
                role: "supplier",
                magnitude: 0.015,
                basis: "segment axis",
                status: "disclosed",
                is_member: true,
                source_ref: null,
              },
            ],
            asserted_without_magnitude: 12,
          },
          evidence: { source: "company_exposure" },
        },
      ],
    },
  } as unknown as ReportResponse;
}

/** Same report, but assembled without a `chain_exposure` block -- the shape
 *  the coordinator's finding says every chain report on prod is in today
 *  (zero chain reports exist), and the one of `aliasExposures`'s three
 *  null-producing paths no test previously reached. */
function reportOkWithoutExposureBlock(): ReportResponse {
  return {
    state: "ok",
    versions: [
      {
        version_no: 1,
        created_at: "2026-08-27T00:00:00Z",
        status: "published",
      },
    ],
    delta: {
      is_first_version: true,
      manifest: [],
      added: [],
      removed: [],
      moved: [],
      summary: "first version",
    },
    report: {
      report_id: 2,
      report_key: "chain:Networking/Optical",
      report_type: "chain",
      version_no: 1,
      title: "Networking/Optical",
      content_hash: "b".repeat(64),
      status: "published",
      created_at: "2026-08-27T00:00:00Z",
      manifest: {
        engine_version: "fundamentals-v2",
        taxonomy_version: "taxonomy-v1",
        evidence_policy: "exclude",
        as_of: "2026-08-27",
        assembler_version: "chain/1",
        scope: { chain: "Networking/Optical" },
      },
      blocks: [],
    },
  } as unknown as ReportResponse;
}

// --- Route segment rejoin ---------------------------------------------------

describe("chainFromSegments", () => {
  it("rejoins a slash-bearing chain name from its catch-all segments", async () => {
    const { chainFromSegments } =
      await import("@/lib/fundamentalsSection");
    expect(chainFromSegments(["Networking", "Optical"])).toBe(
      "Networking/Optical",
    );
  });

  it("resolves a slash-free chain, which arrives as a one-element array", async () => {
    const { chainFromSegments } =
      await import("@/lib/fundamentalsSection");
    expect(chainFromSegments(["Sector-ETF"])).toBe("Sector-ETF");
  });
});

describe("the chain query value", () => {
  it("keeps the slash raw while still encoding what would split the query", async () => {
    const { _rawSlash } = await import("@/lib/api");
    expect(_rawSlash("Networking/Optical")).toBe("Networking/Optical");
    expect(_rawSlash("R&D/Optical")).toBe("R%26D/Optical");
  });
});

// --- Calendar strip ---------------------------------------------------------

describe("NodeCalendarStrip", () => {
  it("says 'not covered' for a null implied move while still printing a covered one", () => {
    render(<NodeCalendarStrip data={CALENDAR} />);
    const lite = screen.getByTestId("calendar-row-LITE");
    expect(
      within(lite).getByTestId("implied-move-not-covered").textContent,
    ).toBe("not covered");
    expect(within(lite).queryByTestId("implied-move")).toBeNull();
    // The far side of the boundary: a covered print still renders a number.
    const cohr = screen.getByTestId("calendar-row-COHR");
    expect(within(cohr).getByTestId("implied-move").textContent).toMatch(
      /8\.1%/,
    );
    expect(within(cohr).queryByTestId("implied-move-not-covered")).toBeNull();
  });

  it("renders the implied-move snapshot date beside a covered move", () => {
    render(<NodeCalendarStrip data={CALENDAR} />);
    const cohr = screen.getByTestId("calendar-row-COHR");
    expect(within(cohr).getByTestId("implied-move").textContent).toMatch(
      /as of 2026-08-27/,
    );
  });

  it("renders a visible unknown badge for a null session and keeps the row", () => {
    render(<NodeCalendarStrip data={CALENDAR} />);
    const poet = screen.getByTestId("calendar-row-POET");
    expect(within(poet).getByTestId("session-unknown").textContent).toMatch(
      /session unknown/i,
    );
    // Not hidden, and no side was guessed for it.
    expect(within(poet).queryByTestId("session-premarket")).toBeNull();
    expect(within(poet).queryByTestId("session-afterhours")).toBeNull();
    // A classified row still shows its classification.
    expect(
      within(screen.getByTestId("calendar-row-LITE")).getByTestId(
        "session-premarket",
      ),
    ).toBeTruthy();
  });

  it("does not render an absent reaction history like a real one", () => {
    render(<NodeCalendarStrip data={CALENDAR} />);
    const alab = screen.getByTestId("calendar-row-ALAB");
    expect(within(alab).getByTestId("reactions-absent").textContent).toMatch(
      /no reaction history held/i,
    );
    expect(within(alab).queryByTestId("reactions")).toBeNull();
    const cohr = screen.getByTestId("calendar-row-COHR");
    expect(within(cohr).getByTestId("reactions")).toBeTruthy();
    expect(within(cohr).queryByTestId("reactions-absent")).toBeNull();
  });

  it("draws a visible mark for a measured 0.0 reaction, not a zero-radius circle", () => {
    // CALENDAR reactions are constructed shapes, per the file header -- there
    // is no real reaction row to freeze at exactly 0.0 without migrations
    // 144-146 applied locally. This 0 is added to the array for the sole
    // purpose of exercising the radius floor.
    const row = calRow({ ticker: "COHR", reactions: [0, -0.0177] });
    render(<NodeCalendarStrip data={{ ...CALENDAR, rows: [row] }} />);
    const svg = screen.getByTestId("reactions");
    const circles = svg.querySelectorAll("circle");
    expect(circles.length).toBe(2);
    // A zero-radius circle still satisfies "the testid exists" -- the point
    // of the floor is that it draws nothing, so the radius itself, not the
    // element's presence, is what a removed floor would fail.
    expect(Number(circles[0].getAttribute("r"))).toBeGreaterThanOrEqual(2);
  });

  it("reads an empty chain calendar as an empty node, not as an error", () => {
    render(<NodeCalendarStrip data={{ ...CALENDAR, rows: [] }} />);
    expect(screen.getByTestId("node-calendar-empty")).toBeTruthy();
    expect(screen.queryByRole("alert")).toBeNull();
  });

  it("names a failed calendar request instead of showing an empty node", () => {
    render(<NodeCalendarStrip data={null} error="API 503 for /calendar" />);
    expect(screen.getByRole("alert").textContent).toMatch(/503/);
    expect(screen.queryByTestId("node-calendar-empty")).toBeNull();
  });
});

// --- Underwriting panel -----------------------------------------------------

describe("NodeUnderwritingPanel", () => {
  it("carries the filing date and the raw filed values in every figure's tooltip", () => {
    render(<NodeUnderwritingPanel rows={UNDERWRITING} />);
    const row = screen.getByTestId("underwriting-row-AAOI");
    const titled = within(row)
      .getAllByTitle(/filed/)
      .map((el) => el.getAttribute("title") ?? "");
    expect(titled.length).toBeGreaterThanOrEqual(3);
    for (const title of titled) {
      expect(title).toMatch(/filed 2026-08-06/);
      expect(title).toMatch(/inventory=278791000/);
      expect(title).toMatch(/cost_of_revenue=138715000/);
      expect(title).toMatch(/stock_based_compensation=4863000/);
      expect(title).toMatch(/common_stock_shares_outstanding=81568000/);
    }
  });

  it("shows the filing date in the row, because a tooltip is not reachable", () => {
    render(<NodeUnderwritingPanel rows={UNDERWRITING} />);
    expect(screen.getByTestId("filed-AAOI").textContent).toBe("2026-08-06");
    // And an absent filing date is named rather than left blank.
    expect(screen.getByTestId("filed-EXTR").textContent).toMatch(
      /no filing date held/i,
    );
  });

  it("states the SBC absence when every name in a non-empty node lacks it", () => {
    render(<NodeUnderwritingPanel rows={UNDERWRITING_NO_SBC} />);
    const note = screen.getByTestId("sbc-absent").textContent ?? "";
    expect(note).toMatch(/stock_based_compensation/);
    expect(note).toMatch(/419 of 420/);
  });

  it("does not state it when a single name carries a value", () => {
    render(<NodeUnderwritingPanel rows={UNDERWRITING} />);
    expect(screen.queryByTestId("sbc-absent")).toBeNull();
  });

  it("does not state it over an EMPTY table, where every() is vacuously true", () => {
    render(<NodeUnderwritingPanel rows={[]} />);
    expect(screen.queryByTestId("sbc-absent")).toBeNull();
    expect(screen.getByTestId("node-underwriting-empty")).toBeTruthy();
  });

  it("never says diluted or dilution over the share count", () => {
    const { container } = render(<NodeUnderwritingPanel rows={UNDERWRITING} />);
    expect(container.textContent ?? "").toMatch(/shares outstanding/i);
    expect(container.textContent ?? "").not.toMatch(/dilut/i);
    for (const el of Array.from(container.querySelectorAll("[title]"))) {
      expect(el.getAttribute("title") ?? "").not.toMatch(/dilut/i);
    }
  });

  it("does not render no_compatible_run and no_coverage alike", () => {
    render(<NodeUnderwritingPanel rows={UNDERWRITING} />);
    const ranNothing = screen.getByTestId("state-CRDO").textContent ?? "";
    const holdsNothing = screen.getByTestId("state-EXTR").textContent ?? "";
    expect(ranNothing).not.toBe(holdsNothing);
    expect(ranNothing).toMatch(/run/i);
    expect(holdsNothing).toMatch(/holds no statements/i);
  });

  it("does not render a stale_run figure as current", () => {
    render(<NodeUnderwritingPanel rows={UNDERWRITING} />);
    // CIEN carries state: "stale_run" in the fixture.
    expect(screen.getByTestId("state-CIEN").textContent).toMatch(
      /superseded engine version/i,
    );
  });

  it("names a failed underwriting request instead of claiming the node is empty", () => {
    render(
      <NodeUnderwritingPanel rows={[]} error="API 500 for /underwriting" />,
    );
    expect(screen.getByRole("alert").textContent).toMatch(/500/);
    expect(screen.queryByTestId("node-underwriting-empty")).toBeNull();
  });
});

// --- Alias questions --------------------------------------------------------

describe("NodeAliasQuestions", () => {
  it("names both open questions, APH and CIEN, with their candidate tags", () => {
    render(
      <NodeAliasQuestions
        exposures={[
          { ticker: "APH", magnitude: 0.615, basis: "alias", is_member: false },
          {
            ticker: "CIEN",
            magnitude: 0.015,
            basis: "segment",
            is_member: true,
          },
        ]}
      />,
    );
    expect(screen.getByTestId("alias-question-APH").textContent ?? "").toMatch(
      /communicationssolutions/,
    );
    const cien = screen.getByTestId("alias-question-CIEN").textContent ?? "";
    expect(cien).toMatch(/81%/);
    expect(cien).toMatch(/70%/);
  });

  it("reads the published magnitude and membership when the block is available", () => {
    render(
      <NodeAliasQuestions
        exposures={[
          { ticker: "APH", magnitude: 0.615, basis: "alias", is_member: false },
        ]}
      />,
    );
    const aph = screen.getByTestId("alias-question-APH").textContent ?? "";
    expect(aph).toMatch(/61\.5%/);
    expect(aph).toMatch(/NOT a member/);
    expect(screen.queryByTestId("alias-no-report")).toBeNull();
  });

  it("says no published report backs the flags rather than asserting them", () => {
    render(<NodeAliasQuestions exposures={null} />);
    expect(screen.getByTestId("alias-no-report").textContent).toMatch(
      /no published report/i,
    );
    // The questions themselves still render -- they are the deliverable.
    expect(screen.getByTestId("alias-question-APH")).toBeTruthy();
    expect(screen.getByTestId("alias-question-CIEN")).toBeTruthy();
    // ...but no membership fact is claimed for either.
    expect(
      screen.getByTestId("alias-question-APH").textContent ?? "",
    ).not.toMatch(/member of this chain/);
  });
});

// --- Limits -----------------------------------------------------------------

describe("NodeLimits", () => {
  it("names all four inputs it does not attempt", () => {
    render(<NodeLimits />);
    for (const input of [
      "ASP / mix",
      "Capacity",
      "Lead times",
      "Qualification status",
    ]) {
      expect(screen.getByTestId(`node-limit-${input}`)).toBeTruthy();
    }
  });

  it("reports both probe outcomes and the alias caveat", () => {
    render(<NodeLimits />);
    const probe = screen.getByTestId("node-limits-probe").textContent ?? "";
    expect(probe).toMatch(/stock_based_compensation/);
    expect(probe).toMatch(/not present in the\s+ingested statements/);
    expect(
      screen.getByTestId("node-limits-alias-caveat").textContent ?? "",
    ).toMatch(/changing a\s+rule changes these numbers/);
  });
});

// --- The page ---------------------------------------------------------------

vi.mock("next/navigation", () => ({
  notFound: () => {
    throw new Error("NEXT_NOT_FOUND");
  },
}));

const deskCalendar = vi.fn();
const nodeUnderwriting = vi.fn();
const researchReport = vi.fn();
const assembleResearchReport = vi.fn();

vi.mock("@/lib/api", async (importOriginal) => {
  const actual = await importOriginal<typeof import("@/lib/api")>();
  return {
    ...actual,
    api: {
      ...actual.api,
      deskCalendar: (...a: unknown[]) => deskCalendar(...a),
      nodeUnderwriting: (...a: unknown[]) => nodeUnderwriting(...a),
      researchReport: (...a: unknown[]) => researchReport(...a),
      assembleResearchReport: (...a: unknown[]) => assembleResearchReport(...a),
    },
  };
});

async function renderPage(segments = ["Networking", "Optical"]) {
  const { default: NodePage } =
    await import("@/app/fundamentals/ai-semi/[...node]/page");
  return render(
    await NodePage({ params: Promise.resolve({ node: segments }) }),
  );
}

describe("the node page", () => {
  beforeEach(() => {
    vi.clearAllMocks();
    deskCalendar.mockResolvedValue(CALENDAR);
    nodeUnderwriting.mockResolvedValue(UNDERWRITING);
    researchReport.mockResolvedValue(reportOk());
  });

  it("asks the desk for this chain by its rejoined name", async () => {
    await renderPage();
    expect(deskCalendar).toHaveBeenCalledWith("ai-semi", "Networking/Optical");
    expect(nodeUnderwriting).toHaveBeenCalledWith(
      "ai-semi",
      "Networking/Optical",
    );
  });

  it("raises notFound for a chain this desk does not contain", async () => {
    // Task 13 answers 404 -> `allow404` -> null for an unknown chain.
    deskCalendar.mockResolvedValue(null);
    nodeUnderwriting.mockResolvedValue(null);
    const { default: NodePage } =
      await import("@/app/fundamentals/ai-semi/[...node]/page");
    await expect(
      NodePage({ params: Promise.resolve({ node: ["Nope"] }) }),
    ).rejects.toThrow("NEXT_NOT_FOUND");
  });

  it("renders a chain that exists and holds nothing as a real, empty node", async () => {
    deskCalendar.mockResolvedValue({ ...CALENDAR, rows: [] });
    nodeUnderwriting.mockResolvedValue([]);
    await renderPage();
    expect(screen.getByTestId("node-calendar-empty")).toBeTruthy();
    expect(screen.getByTestId("node-underwriting-empty")).toBeTruthy();
    // The node is still a node: its limits and its open questions stand.
    expect(screen.getByTestId("node-limits")).toBeTruthy();
    expect(screen.getByTestId("node-alias-questions")).toBeTruthy();
  });

  it("replays the stored report and never assembles one", async () => {
    await renderPage();
    expect(screen.getByText(/replays from its stored blocks/i)).toBeTruthy();
    // The caption text alone is a proxy a stub could carry without being
    // ReportView. The content hash is derived from the fixture's actual
    // report and is not something a caption-only substitute would emit.
    expect(screen.getByText("a".repeat(16))).toBeTruthy();
    expect(assembleResearchReport).not.toHaveBeenCalled();
    expect(screen.queryByTestId("node-report-absent")).toBeNull();
  });

  it("reads the exposure block out of the stored report for the alias flags", async () => {
    await renderPage();
    expect(screen.getByTestId("alias-question-APH").textContent ?? "").toMatch(
      /61\.5%/,
    );
    expect(screen.queryByTestId("alias-no-report")).toBeNull();
  });

  it("says no published report backs the alias flags when the report holds no chain_exposure block", async () => {
    // Only one of `aliasExposures`'s three null-producing paths was
    // previously reached from the page: `state: "no_report"`. This is the
    // one where a report exists but was assembled without the block -- the
    // shape every chain report on prod is in today (zero chain reports
    // exist there).
    researchReport.mockResolvedValue(reportOkWithoutExposureBlock());
    await renderPage();
    expect(screen.getByTestId("alias-no-report")).toBeTruthy();
    expect(
      screen.queryByText(/carries no exposure row for this name/i),
    ).toBeNull();
  });

  it("names a failed calendar request as a failure, not as an empty node", async () => {
    // No page-level test previously made `deskCalendar` reject -- the
    // component-level test injects `error` directly, which pins only the
    // component's own rendering, not the page's wiring of it.
    deskCalendar.mockRejectedValue(
      new Error("API 503 for /fundamentals/ai-semi/node/calendar: down"),
    );
    await renderPage();
    expect(screen.getByRole("alert").textContent).toMatch(/503/);
    expect(screen.queryByTestId("node-calendar-empty")).toBeNull();
  });

  it("names a failed underwriting request as a failure, not as an empty node", async () => {
    nodeUnderwriting.mockRejectedValue(
      new Error("API 500 for /fundamentals/ai-semi/node/underwriting: down"),
    );
    await renderPage();
    expect(screen.getByRole("alert").textContent).toMatch(/500/);
    expect(screen.queryByTestId("node-underwriting-empty")).toBeNull();
  });

  it("says no published report backs the node, and still renders the node", async () => {
    researchReport.mockResolvedValue({
      state: "no_report",
      reason: "no report has been assembled for chain:Networking/Optical",
      versions: [],
    } as unknown as ReportResponse);
    await renderPage();
    expect(screen.getByTestId("node-report-absent").textContent).toMatch(
      /No published report backs this node/,
    );
    expect(screen.getByTestId("alias-no-report")).toBeTruthy();
    // The rest of the page is unaffected.
    expect(screen.getByTestId("calendar-row-COHR")).toBeTruthy();
    expect(screen.getByTestId("underwriting-row-AAOI")).toBeTruthy();
  });

  it("distinguishes an unaddressable report route from an absent report", async () => {
    // A slash-named chain cannot be a path segment: uvicorn unquotes %2F before
    // Starlette routes, so the reports route answers 404. That is not evidence
    // about whether a report exists.
    researchReport.mockRejectedValue(
      new Error(
        "API 404 for /api/research/reports/chain/Networking%2FOptical: ",
      ),
    );
    await renderPage();
    const note =
      screen.getByTestId("node-report-unaddressable").textContent ?? "";
    expect(note).toMatch(/addressing failure/i);
    expect(note).not.toMatch(/No published report backs this node/);
    expect(screen.queryByTestId("node-report-absent")).toBeNull();
  });

  it("names a failed report request as a failure, not as an absence", async () => {
    researchReport.mockRejectedValue(
      new Error("API 503 for /api/research: down"),
    );
    await renderPage();
    expect(screen.getByTestId("node-report-absent").textContent).toMatch(
      /The report request failed: API 503/,
    );
    expect(screen.queryByTestId("node-report-unaddressable")).toBeNull();
  });

  it("offers no sort, rank or score affordance -- this desk lists", async () => {
    const { container } = await renderPage();
    for (const el of Array.from(
      container.querySelectorAll("button, select, a"),
    )) {
      expect(el.textContent ?? "").not.toMatch(/sort|rank|score/i);
    }
    expect(container.querySelector("[data-sort], [aria-sort]")).toBeNull();
  });
});
