import { BOARD_QUESTION_LABEL, type BoardQuestion } from "./domain/BoardPanel";

/**
 * The desk's key: what the provenance tags mean, and what the seven questions are.
 *
 * ### Why it lives in the layout and not on a tab
 *
 * The board is one page, so it prints this once above its tab strip and every tab is read
 * underneath it. The desk is nine routes, and the equivalent of "once, above the tabs" is
 * the layout — which is also the only placement that makes the key true of the tab you are
 * actually looking at. Putting it on the overview tab alone would explain the vocabulary
 * on the one tab that needs it least.
 *
 * ### Why it is not optional chrome
 *
 * `BoardPanel` requires every panel to declare which of Q1–Q7 it answers — the board's own
 * acceptance test, encoded as a non-empty tuple so a panel answering none does not compile.
 * The desk therefore renders sixty-odd `Q4`-style chips, and until this landed the page
 * never said what any of them meant. The same for `REAL` / `COMPUTED` / `PLANNED`: a panel
 * claiming its numbers are arithmetic on published values is making a real claim, and a
 * reader who cannot decode the badge cannot check it.
 *
 * The wording is the board's, verbatim, because it is a definition rather than a reading —
 * there is nothing here to derive and nothing that goes stale.
 */
const QUESTIONS: readonly { q: BoardQuestion; name: string; ask: string }[] = [
  { q: "Q1", name: "STATE", ask: "Which macro world am I in?" },
  { q: "Q2", name: "PRICING", ask: "What gap vs. the official path?" },
  { q: "Q3", name: "DISAGREEMENT", ask: "Which evidence contradicts itself?" },
  { q: "Q4", name: "TRANSMISSION", ask: "Is the textbook chain intact?" },
  { q: "Q5", name: "POSITIONING", ask: "Who is on which side, how crowded?" },
  { q: "Q6", name: "FALSIFIERS", ask: "What event flips the call?" },
  { q: "Q7", name: "TRUST", ask: "How fresh? What does the desk refuse?" },
];

export function BoardLegend() {
  return (
    <>
      <div className="legend-strip">
        <span>
          <b>Provenance:</b>
        </span>
        <span>
          <span className="tag real">REAL</span> production DB / API value,
          verbatim
        </span>
        <span>
          <span className="tag comp">COMPUTED</span> arithmetic on REAL values
          (formula shown)
        </span>
        <span>
          <span className="tag plan">PLANNED</span> proposed panel, data not yet
          ingested
        </span>
        <span>
          <span className="tag q">Q1–Q7</span> which PM question a panel answers
        </span>
      </div>

      <div className="pmq">
        {QUESTIONS.map((item) => (
          <div className="q" key={item.q} title={BOARD_QUESTION_LABEL[item.q]}>
            <b>
              {item.q} {item.name}
            </b>
            <span>{item.ask}</span>
          </div>
        ))}
      </div>
    </>
  );
}
