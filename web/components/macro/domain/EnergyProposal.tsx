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
      title="Current coverage"
      questions={["Q7"]}
      basis="REFERENCE"
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
                {/* `.state` at its own size, not shrunk by an inline override.
                 *
                 * The board puts a `.tag` in this cell rather than a `.state`, and the
                 * inline `fontSize: 10` here was reaching for a tag's size while keeping a
                 * pill's class — which made the element disagree with its own definition
                 * and was what the board/live pixel compare caught on t6.
                 *
                 * It stays a `.state` rather than becoming a `.tag`: the tag vocabulary is
                 * a PROVENANCE one (real / computed / planned) and this column's verdicts
                 * are ok / warning / neutral. Mapping the second onto the first to win a
                 * font size would change what the cell claims. */}
                <td>
                  <span className={TONE_CLASS[row.tone]}>{row.verdict}</span>
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BoardRead testId="energy-inventory-read">
        Dated repository audit, not a live market reading. Raw oil contracts
        already land in the lake; the macro store still has no energy series.
      </BoardRead>
    </BoardPanel>
  );
}

/** The board's three-step route. Each step standalone, in its stated order. */
const ROUTE: readonly { step: string; title: string; body: string }[] = [
  {
    step: "P1",
    title: "FRED spot series",
    body: "Ingest WTI, Brent and Henry Hub through the existing macro series path. This unlocks levels, year-on-year changes, Brent−WTI and the gold÷oil anchor.",
  },
  {
    step: "P2",
    title: "Lake futures term structure",
    body: "Turn existing CL and BZ contract months into contango, backwardation and roll-shape readings.",
  },
  {
    step: "P3",
    title: "Natural gas and its seasonality",
    body: "Compare the current contract with its own ten-year same-month distribution.",
  },
];

export function EnergyRoutePanel() {
  return (
    <BoardPanel
      id="energy-route"
      title="Build path"
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
        Each step produces a usable reading on its own; P1 needs no new
        infrastructure.
      </BoardRead>
    </BoardPanel>
  );
}

/** What the panels would be, once there is anything to draw. No values, by construction. */
const PROPOSED: readonly { title: string; body: string }[] = [
  {
    title: "WTI / Brent levels + spread",
    body: "Two spot series and their spread after P1.",
  },
  {
    title: "Futures term structure",
    body: "Contango or backwardation across existing contract months after P2.",
  },
  {
    title: "NG seasonal band",
    body: "Current gas against its same-month history after P3.",
  },
];

export function EnergyProposedPanels() {
  return (
    <div className="grid g3" style={{ marginTop: 12 }}>
      {PROPOSED.map((proposal) => (
        <div
          className="ghost"
          data-testid="energy-proposed-ghost"
          key={proposal.title}
        >
          <h3>{proposal.title}</h3>
          <span>{proposal.body}</span>
        </div>
      ))}
    </div>
  );
}

export function EnergyDisciplinePanel() {
  return (
    <BoardRefusal kind="HONEST BOUNDARY" testId="energy-discipline">
      No energy state until thresholds are measured. Until then this tab may
      show levels, spreads and percentiles only.
    </BoardRefusal>
  );
}
