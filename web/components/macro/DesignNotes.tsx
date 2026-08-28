/**
 * Tab 08 — the desk's own design record.
 *
 * Static prose. No data path, no fetch, no client island. Everything here is drawn from
 * the desk's plan document rather than from a live surface, which is precisely why it
 * can be the first tab to ship: it cannot be wrong about production because it makes no
 * claim about production.
 *
 * What belongs on this tab: the rules the desk holds itself to, and the reasons. What
 * does not: any number a publisher could have answered instead.
 *
 * It is UNLISTED as of 2026-08-28 (`audience: "operator"` in the registry). The board's
 * own t8 opens by saying so — "this tab is for you (the operator) and does not ship on
 * the final page" — and the route stays registered so the operator keeps the URL.
 */
export function DesignNotes() {
  return (
    <div data-testid="macro-design-notes" style={PAGE}>
      <header style={{ marginBottom: 20 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>
          Design Notes
        </h1>
        <p style={LEDE}>
          The macro desk&rsquo;s design record: what it refuses to do, what it
          has to keep proving, and which of its empty slots are deliberate
          rather than broken. These are notes about the desk, not readings from
          it — nothing on this tab is computed, and nothing on it moves.
        </p>
        <p style={LEDE}>
          <strong>This tab is unlisted.</strong> It is reachable at{" "}
          <code>/macro/notes</code> and is deliberately absent from the tab
          strip: the design board it was written from says it is for the
          operator and does not ship on the desk itself. Nothing above the fold
          of any other tab depends on it.
        </p>
      </header>

      <Section
        title="Four things this desk will not do"
        lede="Restated here so they cannot drift. Each is a rule about the desk's shape, not a preference about its content."
      >
        <Note title="No composite">
          Four domains publish independently, on four schedules, from four
          engines. Averaging four differently-grounded answers into one number
          would hide exactly the disagreements this desk exists to show. It is
          forbidden by test, not by convention.
        </Note>
        <Note title="Macro never derives equity">
          The arrow runs equity → reads → factor, never the reverse. A macro
          domain publishes a state; an equity surface may consume it. No macro
          tab may reach the other way and produce a name-level or index-level
          conclusion of its own.
        </Note>
        <Note title="The SPX vol card is not part of this desk">
          Its &ldquo;macro&rdquo; means index-level volatility, which is a
          different subject wearing the same word. It stays on the regime desk.
          A link is not a card: if the desk ever points at it, it points away
          from itself and says so.
        </Note>
        <Note title="No new analytics">
          The domain tabs are a presentation merge of pages that already
          existed. A panel that cannot be built from a field some publisher
          already answers is out of scope for the merge and belongs in a spec of
          its own.
        </Note>
      </Section>

      <Section
        title="Invariants that stay test-enforced"
        lede="Ten rules with tests behind them. A rule with no test is a preference, and preferences erode."
      >
        <ol style={LIST}>
          <li style={LIST_ITEM}>
            No composite anywhere in the desk&rsquo;s own chrome — no score, no
            allocation, no probability.
          </li>
          <li style={LIST_ITEM}>
            Empty slots are <strong>three-state</strong>: answered, request
            failed, or never computed. Collapsing the last two reports a missing
            engine as a broken network and sends the operator looking in the
            wrong place.
          </li>
          <li style={LIST_ITEM}>
            The four policy paths are never averaged. Four forecasters
            disagreeing is the finding; their mean is not.
          </li>
          <li style={LIST_ITEM}>
            <code style={CODE}>UNKNOWN</code> is not{" "}
            <code style={CODE}>NEUTRAL</code>. One is an absence of an answer,
            the other is an answer.
          </li>
          <li style={LIST_ITEM}>
            SEP dots stay anonymous. The payload is{" "}
            <code style={CODE}>(rate_percent, participant_count)</code> because
            an anonymous dot belongs to no named participant, and a chart that
            implies otherwise invents an attribution the source never made.
          </li>
          <li style={LIST_ITEM}>
            Gold valuation keeps its <strong>⚠ NEVER A SIZING INPUT</strong>{" "}
            marking.
          </li>
          <li style={LIST_ITEM}>
            Refusals describe; they never prescribe. A panel explaining what the
            desk cannot answer must not turn that into an instruction.
          </li>
          <li style={LIST_ITEM}>
            The chain verdict is fetched <em>beside</em> the domain cards, never
            instead of them, and its own failure renders as{" "}
            <code style={CODE}>macro-chain-unassembled</code> — never as a clean
            chain.
          </li>
          <li style={LIST_ITEM}>
            Chart scale <code style={CODE}>k</code> stays within{" "}
            <code style={CODE}>[0.90, 1.10]</code> on every SVG this desk draws,
            measured at a viewport pinned in the spec itself. The gate must also
            assert it found at least one SVG: a check that passes on an empty
            set is not a check.
          </li>
          <li style={LIST_ITEM}>
            A domain&rsquo;s reported confidence equals what its own confidence
            reasons fold back to, using each term&rsquo;s declared{" "}
            <code style={CODE}>kind</code> alone. The refold is blind to term
            names on purpose — a check that special-cases a term by string
            passes straight through the defect it exists to catch.
          </li>
        </ol>
      </Section>

      <Section
        title="Empty by construction, not by outage"
        lede="These fields are hardcoded at their source and identical on every request. A panel built on one would render the same value forever and read as a measurement. The settlement is to stop rendering them and mark them where they are produced — never to remove the field, which is a contract change for no operator benefit."
      >
        <table style={TABLE}>
          <thead>
            <tr>
              <th style={TH}>Field</th>
              <th style={TH}>Why it is empty</th>
            </tr>
          </thead>
          <tbody>
            {DEAD_FIELDS.map((row) => (
              <tr key={row.field}>
                <td style={TD}>
                  <code style={CODE}>{row.field}</code>
                </td>
                <td style={{ ...TD, color: "var(--text-secondary)" }}>
                  {row.why}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </Section>

      <Section
        title="Chart scale: hold the factor at 1, not the viewBox"
        lede="The one drawing rule this desk needs, because it is the one that fails silently."
      >
        <Note title="What actually happens">
          A responsive SVG — <code style={CODE}>width: 100%</code> with a fixed{" "}
          <code style={CODE}>viewBox</code> — stretches its own internal
          coordinate system to fit the container.{" "}
          <code style={CODE}>font-size</code> lives inside that coordinate
          system, so effective type size is{" "}
          <code style={CODE}>font-size × (container_px ÷ viewBox_width)</code>.
          Text included. Two charts declaring the same font size render at
          different sizes whenever their frames differ.
        </Note>
        <Note title="The rule">
          Pick the frame whose width matches the container the chart will
          actually occupy, and then{" "}
          <code style={CODE}>font-size=&quot;10&quot;</code> means 10px. Reuse
          the existing wide and narrow frames; a third column width means
          extending that module, not inventing a new primitive beside it.
          Re-measure both frames in a real browser whenever the shell around
          them changes — a tab bar above the content moves the grid cell the
          narrow frame was sized to.
        </Note>
        <Note title="The standing trap">
          Never set{" "}
          <code style={CODE}>preserveAspectRatio=&quot;none&quot;</code> on a
          chart that draws <code style={CODE}>&lt;text&gt;</code>: it distorts
          labels horizontally. It is legitimate only for text-free sparklines. A
          hand-tuned fractional font size is a scale-compensation hack for one
          frame, not a design token, and must not be copied to a second chart.
        </Note>
      </Section>
    </div>
  );
}

/** §4.2's table, carried as data so a row cannot be half-edited. */
const DEAD_FIELDS: readonly { field: string; why: string }[] = [
  {
    field: "rates.events[]",
    why: "The item model has zero producers anywhere in the backend; the list is always empty.",
  },
  {
    field: "gold.cyclical.two_force_text",
    why: "Both halves are an em-dash literal. The render was already deleted.",
  },
  {
    field: "gold.decomposition_rows[]",
    why: "Deliberately unpopulated, with the reasoning recorded at the producing site.",
  },
  {
    field: "gold.valuation.gold_oil_ratio_percentile",
    why: "Declared and never assigned — the declaration is its only occurrence, so it is always null.",
  },
  {
    field: "gold.structural.xau_cny_premium_pct",
    why: "Always null; no source feeds it today.",
  },
  {
    field: "gold.structural.cb_52w_pct",
    why: "Always null; same missing source.",
  },
  {
    field: "COMEX vault_oz",
    why: "Always null; marked at the producing site.",
  },
  {
    field: "gold_spx_ratio_percentile",
    why: "Computed from a series that is always empty, and self-declared as such through the inputs it lists.",
  },
];

function Section({
  title,
  lede,
  children,
}: {
  title: string;
  lede: string;
  children: React.ReactNode;
}) {
  return (
    <section style={SECTION}>
      <h2 style={H2}>{title}</h2>
      <p style={SECTION_LEDE}>{lede}</p>
      <div style={{ display: "grid", gap: 10 }}>{children}</div>
    </section>
  );
}

function Note({
  title,
  children,
}: {
  title: string;
  children: React.ReactNode;
}) {
  return (
    <div style={NOTE}>
      <strong style={NOTE_TITLE}>{title}</strong>
      <p style={NOTE_BODY}>{children}</p>
    </div>
  );
}

const PAGE = {
  padding: 24,
  maxWidth: 1100,
  margin: "0 auto",
  color: "var(--text-primary)",
} as const;

const LEDE = {
  margin: "6px 0 0",
  fontSize: 13,
  color: "var(--text-secondary)",
  maxWidth: 720,
} as const;

const SECTION = { marginBottom: 24 } as const;

const H2 = {
  margin: 0,
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  letterSpacing: "0.08em",
  textTransform: "uppercase",
  color: "var(--text-primary)",
} as const;

const SECTION_LEDE = {
  margin: "6px 0 12px",
  fontSize: 12.5,
  color: "var(--text-muted)",
  maxWidth: 780,
} as const;

const NOTE = {
  border: "1px solid var(--border-dim)",
  borderRadius: 6,
  padding: "10px 12px",
  background: "var(--bg-panel)",
} as const;

const NOTE_TITLE = { fontSize: 13, display: "block" } as const;

const NOTE_BODY = {
  margin: "4px 0 0",
  fontSize: 12.5,
  color: "var(--text-secondary)",
} as const;

const LIST = {
  margin: 0,
  paddingLeft: 20,
  fontSize: 12.5,
  color: "var(--text-secondary)",
} as const;

const LIST_ITEM = { marginBottom: 6 } as const;

const CODE = {
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
} as const;

const TABLE = {
  width: "100%",
  borderCollapse: "collapse",
  fontSize: 12.5,
} as const;

const TH = {
  textAlign: "left",
  padding: "6px 8px",
  borderBottom: "1px solid var(--border-dim)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
  letterSpacing: "0.05em",
  textTransform: "uppercase",
  color: "var(--text-muted)",
} as const;

const TD = {
  padding: "6px 8px",
  borderBottom: "1px solid var(--border-dim)",
  verticalAlign: "top",
} as const;
