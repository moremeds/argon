import { BoardPanel, BoardRead, BoardRefusal } from "./BoardPanel";

/**
 * Board tab 06 — Energy · Proposal.
 *
 * The only tab on this desk that ships with no live data path, and it says so in its own
 * heading. It exists because the board put a proposal on the desk rather than in a
 * document nobody opens: energy is the supply-side driver of inflation, the denominator
 * of the gold÷oil anchor, and a volatility input on the dollar side — three places where
 * the desk currently has a hole it cannot see.
 *
 * ### The one panel carrying numbers is a DATED FINDING, not a reading
 *
 * The board's inventory table is the result of one enumeration run on 2026-08-26 — every
 * series in the macro store, plus a directory inventory of the lake's commodity/futures
 * prefixes. Those counts were true when the enumeration ran and nothing on this page
 * re-checks them. So the panel names its measurement date and its method in its own
 * provenance line, and the read beneath says plainly that it is a citation.
 *
 * That is the difference between this and every other panel on the desk: elsewhere a
 * number is what an endpoint answered a moment ago, and a stale one is a bug. Here a
 * number is what somebody measured on a stated day, and the date IS the number's meaning.
 * Dressing it as live would be the more comfortable choice and the dishonest one.
 *
 * ### No label, and that is the discipline the tab is arguing for
 *
 * An energy domain state — SUPPLY_TIGHT, GLUT, whatever — needs its own spec and its own
 * threshold measurement before it can be published, exactly as the four existing domains
 * did. Until then this tab could only ever show levels, spreads and percentiles. Shipping
 * a fifth label because four already exist is how a desk acquires a state nobody measured.
 */

/** The 2026-08-26 enumeration, carried as a citation with its own date attached. */
const INVENTORY: readonly {
  source: string;
  status: string;
  verdict: string;
  tone: "ok" | "warn" | "neutral";
}[] = [
  {
    source: "macro store · all series enumerated",
    status: "0 energy series",
    verdict: "greenfield",
    tone: "warn",
  },
  {
    source: "livewire lake · WTI (CL)",
    status: "5 contract months landing raw",
    verdict: "already collecting",
    tone: "ok",
  },
  {
    source: "livewire lake · Brent (BZ)",
    status: "4 contract months landing raw",
    verdict: "already collecting",
    tone: "ok",
  },
  {
    source: "livewire lake · natural gas (NG)",
    status: "none",
    verdict: "missing",
    tone: "warn",
  },
  {
    source: "argon code scaffolding",
    status: "zero hits",
    verdict: "no legacy baggage",
    tone: "neutral",
  },
];

const TONE_CLASS: Record<"ok" | "warn" | "neutral", string> = {
  ok: "state okst",
  warn: "state warnst",
  neutral: "state neust",
};

/** The date the enumeration ran. Rendered, never implied — see the block above. */
const MEASURED_ON = "2026-08-26";

export function EnergyInventoryPanel() {
  return (
    <BoardPanel
      id="energy-inventory"
      title="Data inventory · findings"
      questions={["Q7"]}
      basis="REAL"
      sourceLabel="Measured"
      source={
        <>
          {MEASURED_ON} — full distinct-series enumeration over the macro
          observation and series tables, plus a directory inventory of the
          lake&apos;s commodity and futures prefixes. A one-off run, not a live
          check: nothing on this page re-reads these counts.
        </>
      }
    >
      <div className="tbl-wrap">
        <table data-testid="energy-inventory-table">
          <thead>
            <tr>
              <th>Source</th>
              <th>Status</th>
              <th>Verdict</th>
            </tr>
          </thead>
          <tbody>
            {INVENTORY.map((row) => (
              <tr key={row.source}>
                <td>{row.source}</td>
                <td>{row.status}</td>
                <td>
                  <span
                    className={TONE_CLASS[row.tone]}
                    style={{ fontSize: 10 }}
                  >
                    {row.verdict}
                  </span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BoardRead testId="energy-inventory-read">
        <b>These counts are a citation, not a reading.</b> They were true when
        the enumeration ran on {MEASURED_ON} and nothing here re-checks them, so
        the date is part of the claim rather than a footnote to it. The finding
        that matters is the shape: the raw contract data is{" "}
        <b>already landing</b> in the lake while the macro store has no energy
        series at all, which makes the first step an ingest rather than an
        acquisition.
      </BoardRead>
    </BoardPanel>
  );
}

/** The board's three-step route. Each step standalone, in its stated order. */
const ROUTE: readonly { step: string; title: string; body: string }[] = [
  {
    step: "P1",
    title: "FRED spot series",
    body: "WTI, Brent and Henry Hub through the existing macro series ingest channel — zero new infrastructure. Unlocks same-day: levels and year-on-year, the Brent−WTI spread, the gold÷oil valuation anchor whose cell is null today, and a rolling correlation between WTI year-on-year and breakevens, reusing the gold gauge's own transmission methodology.",
  },
  {
    step: "P2",
    title: "Lake futures term structure",
    body: "The CL and BZ contract months already landing raw become a term-structure panel — contango, backwardation and roll shape. This is the part a spot series cannot give at all, which is why it is a separate step rather than an extension of the first.",
  },
  {
    step: "P3",
    title: "Natural gas and its seasonality",
    body: "Once an NG series lands, the panel is the current month's price percentile inside its own ten-year same-month distribution. Describe first, measure later — seasonality is gas's first-class property, and copying the oil panel onto it would be answering a different question with the same picture.",
  },
];

export function EnergyRoutePanel() {
  return (
    <BoardPanel
      id="energy-route"
      title="Onboarding route · three steps, each standalone"
      questions={["Q7"]}
      basis="PLANNED"
      sourceLabel="Status"
      source="no step has been started; each is independently shippable and none blocks the desk"
    >
      <ol
        style={{
          margin: 0,
          paddingLeft: 18,
          fontSize: 12.5,
          lineHeight: 1.6,
          color: "var(--text-secondary)",
        }}
        data-testid="energy-route-list"
      >
        {ROUTE.map((r) => (
          <li key={r.step} style={{ marginTop: 6 }}>
            <b>
              {r.step} · {r.title}
            </b>{" "}
            — {r.body}
          </li>
        ))}
      </ol>
      <BoardRead>
        Each step stands alone deliberately. A route whose value arrives only at
        the end is a route that gets abandoned halfway and leaves nothing; this
        one lights a specific empty cell at every stage, and the first stage
        needs no new infrastructure at all.
      </BoardRead>
    </BoardPanel>
  );
}

/** What the panels would be, once there is anything to draw. No values, by construction. */
const PROPOSED: readonly { title: string; body: string }[] = [
  {
    title: "WTI / Brent levels + spread",
    body: "Two series and a Brent−WTI spread bar. Lights up after P1. The spread itself carries geopolitical information — it is a transport and quality differential before it is anything else.",
  },
  {
    title: "Futures term structure",
    body: "Contango or backwardation across the contract months already in the lake. Needs P2, and no spot series can substitute for it.",
  },
  {
    title: "Natural gas seasonal band",
    body: "The current month against its own ten-year same-month distribution. Needs P3, and needs its own shape rather than the oil panel's.",
  },
];

export function EnergyProposedPanels() {
  return (
    <BoardPanel
      id="energy-proposed"
      title="What would be drawn, and after which step"
      questions={["Q7"]}
      basis="PLANNED"
      sourceLabel="Status"
      source="descriptions only — no series is ingested, so no panel below can render a value"
    >
      <div className="tbl-wrap">
        <table data-testid="energy-proposed-table">
          <thead>
            <tr>
              <th>Panel</th>
              <th>What it would show</th>
            </tr>
          </thead>
          <tbody>
            {PROPOSED.map((p) => (
              <tr key={p.title}>
                <td>{p.title}</td>
                <td>{p.body}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </BoardPanel>
  );
}

export function EnergyDisciplinePanel() {
  return (
    <BoardRefusal kind="HONEST BOUNDARY" testId="energy-discipline">
      <b>No energy state label, and no fifth domain, until one is measured.</b>{" "}
      A label such as SUPPLY_TIGHT or GLUT needs its own spec and its own
      threshold measurement, exactly as the four existing domains needed theirs.
      Until that exists this tab could honestly show levels, spreads and
      percentiles and nothing else. Adding a fifth label because four already
      exist is how a desk acquires a state nobody measured — and this tab
      inherits the same non-goals as the rest of the desk: it feeds the
      inflation node and the gold valuation anchor, and it makes no predictive
      claim about anything.
    </BoardRefusal>
  );
}
