/**
 * The desk's masthead: what it is for, what it holds, and the question order.
 *
 * The five questions are rendered as a numbered rail because THE ORDER IS THE
 * ARGUMENT: the sample's spending first, then how its groups compare, then
 * what they cost, then what the data cannot say. The rail's titles must match
 * the section headings below it word for word.
 *
 * The stamp's last cell is `vendor calls: 0`. It is not a boast — it is the
 * property that makes this surface replayable: every number below was
 * persisted by a job, so a page read cannot make the desk's cost unbounded or
 * its answer un-reproducible.
 */

import { MONO, labelStyle, panelStyle } from "./DeskSection";

export const QUESTIONS: [string, string][] = [
  [
    "How is sample capex changing?",
    "Quarterly capital expenditure, USD bn, for the USD filers in this sample.",
  ],
  [
    "How do industry groups compare?",
    "Every chain placed by growth, margin and taxonomy layer at once.",
  ],
  [
    "How do case groups compare?",
    "Stage-by-stage growth for the chains whose stages the taxonomy ranks.",
  ],
  [
    "Where is valuation versus own history?",
    "Each name against its own valuation history. Never against its peers.",
  ],
  [
    "What are the data limits?",
    "The measured boundaries of every reading above.",
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
Company-level operating metrics across selected AI-related industry groups
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
        Company-level growth, reported margins and own-history valuation across
        selected AI-related industry groups.{" "}
        <strong style={{ color: "var(--text-primary)" }}>
          This page does not trace payments and does not establish causal
          transmission between groups.
        </strong>{" "}
        The scope is narrow on purpose: it is not a coverage universe and it
        does not rank names against each other.
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
