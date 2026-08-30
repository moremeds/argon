import { Zone } from "@/components/macro/overview/Zone";
import {
  BoardPanel,
  type BoardQuestions,
  type PanelBasis,
} from "@/components/macro/domain/BoardPanel";

/**
 * The two structural elements tabs 01 and 02 are built from, in the board's own grammar.
 *
 * ### What this replaced, and why
 *
 * These were a house hierarchy: `RatesTier` drew a band heading with a lede, and
 * `RatesSection` drew a bordered `<section>` with its own header row. Every panel was
 * full-width and stacked, which is why the pixel compare measured tab 02 at 7839px against
 * the board's 3982 — nearly double the page for the same content, because the board lays
 * these out as pairs and threes and we laid them out as a column.
 *
 * The board has no "tier" element, but it has exactly this device on tab 00: a `.zone`
 * banner naming a band of panels and what bounds it. So the tier becomes a zone and the
 * section becomes a `.panel`, and both keep their ids — the in-page nav on these two tabs
 * links to them, and a design port that broke every anchor would be trading one defect
 * for another.
 */
export function RatesTier({
  id,
  title,
  lede,
  kicker = "Band",
}: {
  id: string;
  title: string;
  lede: string;
  /** The zone's left kicker. Defaults to a neutral word rather than a number, because
   *  unlike tab 00 these bands are not a numbered walk. */
  kicker?: string;
}) {
  return (
    <div id={id} data-testid={`rates-tier-${id}`}>
      <Zone kicker={kicker} label={title} scope={lede} />
    </div>
  );
}

/**
 * One panel.
 *
 * `role="region"` + `aria-label` are carried over from the `<section>` this replaced —
 * the desk's tests query these by accessible name, and more importantly a reader on a
 * screen reader had a labelled landmark per panel before and must still have one.
 *
 * `status` renders as a `.tag`, which is what the board uses for a per-panel state word.
 * It was a filled pill, and a filled pill in a panel header reads as a verdict about the
 * panel's subject rather than a note about its data.
 */
export function RatesSection({
  id,
  title,
  eyebrow,
  questions,
  basis,
  source,
  sourceLabel,
  showQuestions,
  children,
}: {
  id: string;
  title: string;
  eyebrow?: string;
  questions: BoardQuestions;
  basis: PanelBasis;
  source: React.ReactNode;
  sourceLabel?: string;
  showQuestions?: boolean;
  children: React.ReactNode;
}) {
  return (
    <BoardPanel
      id={id}
      title={title}
      questions={questions}
      basis={basis}
      source={source}
      sourceLabel={sourceLabel}
      showQuestions={showQuestions}
    >
      {eyebrow ? <p className="cap">{eyebrow}</p> : null}
      {children}
    </BoardPanel>
  );
}
