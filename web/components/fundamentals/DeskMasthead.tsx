/**
 * The desk's masthead: what it is for, what it holds, and the question order.
 *
 * The five questions are rendered as a numbered rail because THE ORDER IS THE
 * ARGUMENT. A sector screen sorts companies; a chain desk follows one dollar
 * from the balance sheet that commits it to the companies that book it as
 * revenue, and reports where that transmission breaks. You cannot answer
 * question three before question one, so the page is built in that order and
 * the rail says so before the reader scrolls.
 *
 * The stamp's last cell is `vendor calls: 0`. It is not a boast — it is the
 * property that makes this surface replayable: every number below was
 * persisted by a job, so a page read cannot make the desk's cost unbounded or
 * its answer un-reproducible.
 */

import { MONO, labelStyle, panelStyle } from "./DeskSection";

export const QUESTIONS: [string, string][] = [
  [
    "Is the money still coming?",
    "Hyperscaler capex is the only number here not derived from another number here.",
  ],
  [
    "Where does it land?",
    "Every chain placed by growth, margin and position at once.",
  ],
  [
    "Does it transmit?",
    "A dollar's path through the chains whose stages carry an explicit order.",
  ],
  [
    "What am I paying?",
    "Each name against its own valuation history. Never against its peers.",
  ],
  [
    "What would falsify it?",
    "The measured things that would break every reading above.",
  ],
];

/** One accent per question, matching the layer ramp so the rail and the map
 *  speak the same colour language. */
export const QUESTION_TOKENS = [
  "--accent-cool",
  "--extreme",
  "--dislocation",
  "--warning",
  "--signal-strong",
];

function Cell({ label, value }: { label: string; value: string }) {
  return (
    <div style={{ padding: "12px 16px" }}>
      <div style={labelStyle}>{label}</div>
      <div
        style={{
          marginTop: 4,
          fontFamily: MONO,
          fontSize: 18,
          fontWeight: 700,
          letterSpacing: 0.8,
          color: "var(--text-primary)",
          fontVariantNumeric: "tabular-nums",
        }}
      >
        {value}
      </div>
    </div>
  );
}

/**
 * A count, or the absence of one.
 *
 * `null` means the request that would have produced it failed — NOT zero. The
 * two are opposite claims: zero says the desk looked and found nothing, and a
 * masthead reading "chains modelled: 0" beside a panel that is reporting an
 * API error is the page contradicting itself in the reader's favour. The page
 * passes `null` on failure and this prints the dash it deserves.
 */
function count(v: number | null): string {
  return v === null ? "—" : String(v);
}

export function DeskMasthead({
  chains,
  companies,
  capexQuarters,
  layers,
}: {
  chains: number | null;
  companies: number | null;
  capexQuarters: number | null;
  /** Distinct planes the MATRIX actually placed chains on — not
   *  `LAYER_KEYS.length`. The key list is what this client can draw; printing
   *  it as "taxonomy layers" states a fact about the taxonomy that the client
   *  would go on asserting after the taxonomy grew an L6 it silently drops. */
  layers: number | null;
}) {
  return (
    <header>
      <div style={{ ...labelStyle, letterSpacing: 1.8 }}>
        Argon · fundamentals · industry chain desk
      </div>
      <h1
        style={{
          marginTop: 8,
          fontFamily: MONO,
          fontSize: 28,
          fontWeight: 800,
          letterSpacing: 1.4,
          textTransform: "uppercase",
          color: "var(--text-primary)",
        }}
      >
        AI Chain Desk
      </h1>
      <p
        style={{
          marginTop: 6,
          fontSize: 13,
          color: "var(--text-secondary)",
        }}
      >
        One industry, traced from the dollar that pays for it
      </p>

      <div
        style={{
          ...panelStyle,
          marginTop: 16,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
        }}
      >
        <Cell label="chains modelled" value={count(chains)} />
        <Cell label="companies" value={count(companies)} />
        <Cell label="taxonomy layers" value={count(layers)} />
        <Cell label="quarters of capex" value={count(capexQuarters)} />
        <Cell label="vendor calls" value="0" />
      </div>

      <p
        style={{
          marginTop: 20,
          maxWidth: "68ch",
          fontSize: 13.5,
          lineHeight: 1.65,
          color: "var(--text-secondary)",
        }}
      >
        A sector screen sorts companies. A chain desk does something a screen
        cannot: it follows one dollar of spending from the balance sheet that
        commits it to the companies that book it as revenue — and reports where
        that transmission breaks. So the scope is narrow on purpose. This is not
        a coverage universe and it does not rank names against each other. It is{" "}
        <strong style={{ color: "var(--text-primary)" }}>
          one industrial chain — AI and semiconductors — modelled end to end
        </strong>
        , built in the order a fundamental PM has to ask the questions.
      </p>

      <ol
        style={{
          marginTop: 18,
          display: "grid",
          gap: 10,
          gridTemplateColumns: "repeat(auto-fit, minmax(200px, 1fr))",
          listStyle: "none",
        }}
      >
        {QUESTIONS.map(([title, detail], i) => (
          <li
            key={title}
            style={{
              ...panelStyle,
              borderTop: `2px solid var(${QUESTION_TOKENS[i]})`,
              padding: "11px 13px 12px",
            }}
          >
            <div
              style={{
                fontFamily: MONO,
                fontSize: 10,
                fontWeight: 700,
                letterSpacing: 1,
                color: `var(${QUESTION_TOKENS[i]})`,
              }}
            >
              {String(i + 1).padStart(2, "0")}
            </div>
            <div
              style={{
                marginTop: 4,
                fontSize: 12.5,
                fontWeight: 600,
                color: "var(--text-primary)",
              }}
            >
              {title}
            </div>
            <div
              style={{
                marginTop: 4,
                fontSize: 11.5,
                lineHeight: 1.5,
                color: "var(--text-muted)",
              }}
            >
              {detail}
            </div>
          </li>
        ))}
      </ol>
    </header>
  );
}
