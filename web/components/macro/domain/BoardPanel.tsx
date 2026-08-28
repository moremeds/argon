import type { ReactNode } from "react";

/**
 * The frame every board panel wears — the board's own `.panel`, class for class.
 *
 * ### Why this is markup and not a style opinion
 *
 * The first build of these panels answered the board's QUESTIONS while inventing its own
 * typography: a 13px sans bold heading where the board specifies 10px mono uppercase at
 * 1.5px tracking, a plain footer where the board specifies a dashed rule, and no read-rail
 * at all. The information was bound; the design was not. Both bind. So the header, the
 * tag vocabulary and the provenance footer here are the spec's `.panel-h`, `.tag` and
 * `.prov` — see `app/macro/board.css`, which is the spec's stylesheet ported class for
 * class so the two can be diffed.
 *
 * ### The acceptance test, as a type
 *
 * The board's design notes state the rule in one line: _"The seven questions are the
 * acceptance test: every panel must answer at least one, or it gets deleted."_ The port
 * plan's first revision carried neither the questions nor the rule, so nothing on the
 * shipped desk could fail it — which is how tab 03 reached production missing four of its
 * designed panels without anything noticing.
 *
 * `questions` is therefore a REQUIRED, NON-EMPTY tuple. A panel that answers no board
 * question does not render as an untagged panel; it does not compile.
 *
 * ### The provenance vocabulary
 *
 * `basis` is the board's own and means what it means there:
 *
 *   - `REAL` — every number in the body came off an endpoint, unmodified.
 *   - `COMPUTED` — arithmetic performed here, on numbers that came off an endpoint. The
 *     panel must show its formula; the repair table is the case this exists for.
 *   - `PLANNED` — no data path. Prose describing what would be measured, never a value.
 *
 * There is deliberately no `ESTIMATED`. A number nobody published and nobody computed
 * from published inputs has no home on this desk. The tag renders at the END of the
 * provenance line, which is where the board puts it — the claim first, its basis last.
 */
export type BoardQuestion = "Q1" | "Q2" | "Q3" | "Q4" | "Q5" | "Q6" | "Q7";

/** At least one. See the block above — this is the acceptance test, as a type. */
export type BoardQuestions = readonly [BoardQuestion, ...BoardQuestion[]];

export type PanelBasis = "REAL" | "COMPUTED" | "PLANNED";

const BASIS_CLASS: Record<PanelBasis, string> = {
  REAL: "tag real",
  COMPUTED: "tag comp",
  PLANNED: "tag plan",
};

export function BoardPanel({
  id,
  title,
  questions,
  basis,
  sourceLabel = "Source",
  source,
  children,
}: {
  id: string;
  title: string;
  questions: BoardQuestions;
  basis: PanelBasis;
  /** The board's `<b>` prefix on the provenance line: Source · Pipeline · Formula. */
  sourceLabel?: string;
  /** What the body stood on: the endpoint and field for `REAL`, the formula for
   *  `COMPUTED`, the absent data path for `PLANNED`. */
  source: ReactNode;
  children: ReactNode;
}) {
  return (
    <div
      id={id}
      className="panel"
      data-testid={`board-panel-${id}`}
      data-questions={questions.join(" ")}
      data-basis={basis}
    >
      <div className="panel-h">
        <h3>{title}</h3>
        <span className="qs">
          {questions.map((q) => (
            <span key={q} className="tag q" title={BOARD_QUESTION_LABEL[q]}>
              {q}
            </span>
          ))}
        </span>
      </div>

      {children}

      <div className="prov">
        <b>{sourceLabel}</b> {source}{" "}
        <span className={BASIS_CLASS[basis]}>{basis}</span>
      </div>
    </div>
  );
}

/**
 * The board's `.read` — the interpretive paragraph on its accent rail.
 *
 * It is a distinct element rather than a paragraph style because of what the rail means:
 * everything above it is the reading, this is the interpretation OF the reading. A panel
 * with no rail is presenting numbers and drawing no conclusion, which is a legitimate and
 * different thing.
 *
 * `bad` turns the rail red and is for exactly one situation: the panel discovered that
 * its own inputs disagree (an arithmetic that does not reconcile, a citation that failed).
 * It is not for a bearish reading — the desk has no house view to be bearish against.
 */
export function BoardRead({
  bad = false,
  testId,
  children,
}: {
  bad?: boolean;
  testId?: string;
  children: ReactNode;
}) {
  return (
    <p className={bad ? "read bad" : "read"} data-testid={testId}>
      {children}
    </p>
  );
}

/**
 * The board's `.note-refuse` — a dashed callout naming something the desk will not do.
 *
 * The board uses two headings for it, and the distinction is real: `REFUSAL` is a thing
 * we could compute and have decided not to publish; `HONEST BOUNDARY` is a thing we
 * cannot compute because the data is not on our tier. Conflating them would turn a
 * principle into an excuse, or an excuse into a principle.
 */
export function BoardRefusal({
  kind = "REFUSAL",
  testId,
  children,
}: {
  kind?: "REFUSAL" | "HONEST BOUNDARY";
  testId?: string;
  children: ReactNode;
}) {
  return (
    <div className="note-refuse" data-testid={testId}>
      <b>{kind}</b> {children}
    </div>
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
