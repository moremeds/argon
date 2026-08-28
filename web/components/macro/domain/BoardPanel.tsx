import type { ReactNode } from "react";

/**
 * The frame every board panel wears, and the place the board's acceptance test is
 * enforced rather than merely quoted.
 *
 * The board's design notes state the rule in one line: _"The seven questions are the
 * acceptance test: every panel must answer at least one, or it gets deleted."_ The port
 * plan's first revision carried neither the questions nor the rule, so nothing on the
 * shipped desk could fail it — which is how tab 03 reached production missing four of
 * its designed panels without anything noticing.
 *
 * `questions` is therefore a REQUIRED, NON-EMPTY tuple. A panel that answers no board
 * question does not render as an untagged panel; it does not compile. That is the whole
 * reason this frame exists rather than each panel styling its own header — a shared
 * heading style would have been three lines of CSS.
 *
 * `basis` is the board's own provenance vocabulary and means what it means there:
 *
 *   - `REAL` — every number in the body came off an endpoint, unmodified.
 *   - `COMPUTED` — arithmetic performed here, on numbers that came off an endpoint. The
 *     panel must show its formula; the repair table is the case this exists for.
 *   - `PLANNED` — no data path. Prose describing what would be measured, never a value.
 *
 * There is deliberately no `ESTIMATED`. A number nobody published and nobody computed
 * from published inputs has no home on this desk.
 */
export type BoardQuestion = "Q1" | "Q2" | "Q3" | "Q4" | "Q5" | "Q6" | "Q7";

/** At least one. See the block above — this is the acceptance test, as a type. */
export type BoardQuestions = readonly [BoardQuestion, ...BoardQuestion[]];

export type PanelBasis = "REAL" | "COMPUTED" | "PLANNED";

const BASIS_COLOR: Record<PanelBasis, string> = {
  REAL: "var(--positive)",
  COMPUTED: "var(--accent-bg, var(--text-secondary))",
  PLANNED: "var(--text-muted)",
};

export const MONO_LABEL: React.CSSProperties = {
  fontFamily: "var(--font-mono), monospace",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
};

export function BoardPanel({
  id,
  title,
  questions,
  basis,
  source,
  children,
}: {
  id: string;
  title: string;
  questions: BoardQuestions;
  basis: PanelBasis;
  /** What the body stood on, named the way the board names it: the endpoint and field
   *  for `REAL`, the formula for `COMPUTED`, the absent data path for `PLANNED`. */
  source: ReactNode;
  children: ReactNode;
}) {
  return (
    <section
      id={id}
      data-testid={`board-panel-${id}`}
      data-questions={questions.join(" ")}
      data-basis={basis}
      style={{
        background: "var(--bg-panel)",
        border: "1px solid var(--border-dim)",
        borderRadius: 6,
        padding: "14px 16px",
        display: "grid",
        gap: 12,
      }}
    >
      <header
        style={{
          display: "flex",
          alignItems: "baseline",
          justifyContent: "space-between",
          gap: 12,
          flexWrap: "wrap",
        }}
      >
        <h3
          style={{
            margin: 0,
            fontSize: 13,
            fontWeight: 600,
            color: "var(--text-primary)",
          }}
        >
          {title}
        </h3>
        <div style={{ display: "flex", gap: 6, alignItems: "center" }}>
          {questions.map((q) => (
            <span
              key={q}
              title={BOARD_QUESTION_LABEL[q]}
              style={{
                ...MONO_LABEL,
                fontSize: 9,
                padding: "1px 5px",
                border: "1px solid var(--border-dim)",
                borderRadius: 3,
              }}
            >
              {q}
            </span>
          ))}
          <span
            style={{
              ...MONO_LABEL,
              fontSize: 9,
              color: BASIS_COLOR[basis],
              letterSpacing: 1.2,
            }}
          >
            {basis}
          </span>
        </div>
      </header>

      {children}

      <footer
        style={{
          ...MONO_LABEL,
          fontSize: 9,
          letterSpacing: 1.2,
          borderTop: "1px solid var(--border-dim)",
          paddingTop: 8,
          lineHeight: 1.6,
          textTransform: "none",
        }}
      >
        {source}
      </footer>
    </section>
  );
}

/** The board's seven questions, abbreviated. Rendered as the `title` on each
 *  chip so the tag is legible without opening the board. */
export const BOARD_QUESTION_LABEL: Record<BoardQuestion, string> = {
  Q1: "Q1 State — what is the macro world doing",
  Q2: "Q2 Pricing — what is already priced",
  Q3: "Q3 Disagreement — where the evidence contradicts itself",
  Q4: "Q4 Transmission — does the chain still hold",
  Q5: "Q5 Positioning — who is on which side",
  Q6: "Q6 Falsifiers — what would change the answer",
  Q7: "Q7 Trust — how much of this is earned",
};
