import type { ReactNode } from "react";

import { DataDetails } from "../DataDetails";
import { humanizeIdentifier } from "../presentation";

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
 *   - `REFERENCE` — a dated, static audit or method note; never presented as live.
 *
 * There is deliberately no `ESTIMATED`. A number nobody published and nobody computed
 * from published inputs has no home on this desk. The tag renders at the END of the
 * provenance line, which is where the board puts it — the claim first, its basis last.
 */
export type BoardQuestion = "Q1" | "Q2" | "Q3" | "Q4" | "Q5" | "Q6" | "Q7";

/** At least one. See the block above — this is the acceptance test, as a type. */
export type BoardQuestions = readonly [BoardQuestion, ...BoardQuestion[]];

export type PanelBasis = "REAL" | "COMPUTED" | "PLANNED" | "REFERENCE";

export function BoardPanel({
  id,
  title,
  questions,
  basis,
  sourceLabel = "Source",
  source,
  dim = false,
  showQuestions = true,
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
  /**
   * The board's `.panel.dim` — 0.68 opacity.
   *
   * For one situation only: the panel's readings are still true of their own inputs, but
   * a condition published ELSEWHERE says they should not be leaned on. Gold's cyclical
   * lens under a suspended transmission gauge is the case it exists for. It is not a
   * severity, not a staleness marker, and never a substitute for saying why — a dimmed
   * panel must still carry the sentence naming what dimmed it, or it reads as broken.
   */
  dim?: boolean;
  /** Preserve the acceptance metadata without drawing a duplicate badge when the
   *  approved panel uses another header-state device (the Rates sub-state trio). */
  showQuestions?: boolean;
  children: ReactNode;
}) {
  return (
    <div
      id={id}
      className={dim ? "panel dim" : "panel"}
      data-testid={`board-panel-${id}`}
      data-questions={questions.join(" ")}
      data-basis={basis}
      data-dim={dim ? "true" : undefined}
      // The board's markup is a bare `<div class="panel">`. The role and label are added
      // here because a panel IS a discrete labelled division of the tab's content, and
      // that is what the landmark is for — a screen reader otherwise gets eleven
      // unannounced divs where a sighted reader gets eleven framed panels. Nothing about
      // the visual design changes; `.panel-h h3` already carries the same words, and the
      // label points at it rather than duplicating a different string.
      role="region"
      aria-label={title}
    >
      <div className="panel-h">
        <h3>{title}</h3>
        {showQuestions ? (
          <span className="sr-only">
            {questions.map((q) => BOARD_QUESTION_LABEL[q]).join(" · ")}
          </span>
        ) : null}
      </div>

      {children}

      <DataDetails
        basis={basis}
        questions={questions}
        sourceLabel={sourceLabel}
        source={source}
      />
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

/**
 * The board's `.sec-title` + `.sec-sub` — the two lines every tab opens with.
 *
 * Every board tab starts the same way: an `<h2>` naming the tab, the Q-tag strip for the
 * questions the tab as a whole answers, optionally a state pill, and a `.sec-sub`
 * standfirst under it. There is no page lockup and no in-page section nav above it — the
 * desk's tab bar IS the navigation, and a second title inside the tab says the same word
 * twice.
 *
 * Shared rather than written per tab because the alternative already happened once: tabs
 * 03/04 got the board's heading while tabs 01/02 kept the old `/rates` lockup, and the
 * desk read as two products bolted together. One implementation is what stops that
 * recurring the next time a tab is added.
 */
export function BoardSecTitle({
  title,
  questions,
  children,
  aside,
}: {
  title: string;
  /** The questions the TAB answers — the union of its panels'. See the test in
   *  `tests/unit/macroDomainStateTab.test.tsx` that holds the two in agreement. */
  questions: BoardQuestions;
  /** The standfirst. Board `.sec-sub`. */
  children: ReactNode;
  /** Anything that sits on the title row after the tags — a state pill, a provenance
   *  stamp. Kept as a slot because what belongs there differs per tab and the board
   *  shows both cases (t1 has a state pill, t2 has none). */
  aside?: ReactNode;
}) {
  return (
    <>
      <div className="sec-title" data-questions={questions.join(" ")}>
        <h2>{title}</h2>
        <span className="sr-only">
          {questions.map((q) => BOARD_QUESTION_LABEL[q]).join(" · ")}
        </span>
        {aside}
      </div>
      <p className="sec-sub">{children}</p>
    </>
  );
}

/**
 * The board's `.state` pill.
 *
 * ### The tone map is deliberately almost empty
 *
 * Only the two states that name their own distance from a target get a colour. Everything
 * else is neutral, because a state label is not a verdict: `ON_HOLD` is not "good" and
 * `RISING` is not "bad", and painting them would be encoding a house view in a lookup
 * table — the thing the desk's whole no-composite rule exists to prevent.
 *
 * ### The empty slot stays three-state
 *
 * A state that was never computed and a request that failed are different facts, and the
 * pill says which in its own words. Neither wears a state colour: an absent answer must
 * never be able to look like an answer.
 */
const STATE_TONE: Record<string, "okst" | "warnst" | "critst"> = {
  WELL_ABOVE_TARGET: "warnst",
  WELL_BELOW_TARGET: "warnst",
};

export type BoardStateFacts = {
  state: string;
  direction: string;
  confidence: string | number | null | undefined;
};

export function BoardStatePill({
  facts,
  testId,
  absent = "no state — the engine has not run for this instant",
}: {
  facts: BoardStateFacts | null | undefined;
  testId?: string;
  /** What to say when there are no facts. The caller owns this string because only the
   *  caller knows WHICH silence it is — never computed, or never reached. */
  absent?: string;
}) {
  if (!facts) {
    return (
      <span
        className="state neust"
        data-testid={testId}
        style={{ fontWeight: 400 }}
      >
        {absent}
      </span>
    );
  }
  const conf = Number(facts.confidence);
  return (
    <span
      className={`state ${STATE_TONE[facts.state] ?? "neust"}`}
      data-testid={testId}
      data-raw-value={`${facts.state}|${facts.direction}`}
      title={`${facts.state} · ${facts.direction}`}
    >
      {humanizeIdentifier(facts.state)} · {humanizeIdentifier(facts.direction)}
      {Number.isFinite(conf) ? ` · ${Math.round(conf * 100)}% confidence` : ""}
    </span>
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
