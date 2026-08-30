import { BoardPanel, BoardSecTitle } from "./domain/BoardPanel";

const BINDINGS = [
  ["Overview", "Domain states, policy paths, market series, chain snapshot", "Instant"],
  ["Fed", "Rates snapshot, policy comparison, rates state", "Instant"],
  ["Rates", "Rates snapshot, rates sub-states", "Instant"],
  ["Inflation", "Inflation state, cited rates state", "Instant"],
  ["Dollar", "Dollar state", "Instant"],
  ["Gold", "Gold posture, gauge and lens detail", "Observation date"],
  ["Energy", "Dated repository audit and proposed work", "None"],
  ["Factors", "Four domain states", "Instant"],
] as const;

const BASIS = [
  ["Live", "Endpoint values shown without arithmetic"],
  ["Derived", "Browser arithmetic on endpoint values; formula is disclosed"],
  ["Planned", "No data path and no analytical value"],
  ["Reference", "Dated static audit or method note; never presented as live"],
] as const;

export function DesignNotes() {
  return (
    <div className="board" data-testid="macro-design-notes">
      <BoardSecTitle title="Method" questions={["Q7"]}>
        What is live, what is derived, and what this desk refuses to imply.
      </BoardSecTitle>

      <div className="grid g2">
        <BoardPanel
          id="method-basis"
          title="Data types"
          questions={["Q7"]}
          basis="REFERENCE"
          sourceLabel="Rule"
          source="Every analytical panel declares exactly one basis in its metadata."
        >
          <div className="tbl-wrap">
            <table>
              <thead><tr><th>Type</th><th>Meaning</th></tr></thead>
              <tbody>
                {BASIS.map(([basis, meaning]) => (
                  <tr key={basis}><td><b>{basis}</b></td><td>{meaning}</td></tr>
                ))}
              </tbody>
            </table>
          </div>
        </BoardPanel>

        <BoardPanel
          id="method-clocks"
          title="Replay clocks"
          questions={["Q7"]}
          basis="REFERENCE"
          sourceLabel="Rule"
          source="The route registry owns each tab's replay clock."
        >
          <div className="tbl-wrap">
            <table>
              <thead><tr><th>Clock</th><th>Question</th></tr></thead>
              <tbody>
                <tr><td><b>Instant</b></td><td>What had the publisher stored by this time?</td></tr>
                <tr><td><b>Observation date</b></td><td>What market date is this reading about?</td></tr>
                <tr><td><b>None</b></td><td>Static proposal or method; replay does not apply.</td></tr>
              </tbody>
            </table>
          </div>
        </BoardPanel>
      </div>

      <BoardPanel
        id="method-bindings"
        title="Page bindings"
        questions={["Q7"]}
        basis="REFERENCE"
        sourceLabel="Audit"
        source="Reviewed against the server components and API calls on 2026-08-30."
      >
        <div className="tbl-wrap">
          <table data-testid="macro-binding-table">
            <thead><tr><th>Page</th><th>Runtime inputs</th><th>Replay</th></tr></thead>
            <tbody>
              {BINDINGS.map(([page, inputs, clock]) => (
                <tr key={page}><td><b>{page}</b></td><td>{inputs}</td><td>{clock}</td></tr>
              ))}
            </tbody>
          </table>
        </div>
      </BoardPanel>

      <BoardPanel
        id="method-limits"
        title="Desk limits"
        questions={["Q7"]}
        basis="REFERENCE"
        sourceLabel="Policy"
        source="Product boundary; not a data outage."
      >
        <p className="read">
          No composite score, source substitution, browser re-ranking, forecast or
          allocation. Missing data stays missing; each domain keeps its own unit,
          publisher and confidence.
        </p>
      </BoardPanel>
    </div>
  );
}
