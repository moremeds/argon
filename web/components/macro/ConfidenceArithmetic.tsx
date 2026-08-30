import { toNum } from "@/lib/formatters";

import styles from "./ConfidenceArithmetic.module.css";
import { fieldLabel, humanizeText } from "./presentation";
import type { MacroConfidenceReason } from "./types";

/**
 * What actually moved a domain's confidence, and nothing else.
 *
 * Lifted verbatim (behaviour, markup and CSS) from `ConfidenceStrip`, which was private
 * to `components/rates/sections/StateSection.tsx:77-117` and therefore available to
 * exactly one of the four domains that publish a confidence. Plan 2026-08-27 §7 names
 * this lift and P5 owns it: all four `/api/macro/*` domains carry the same
 * `MacroConfidenceReason` shape, so a strip that reads it belongs beside the contract,
 * not inside one consumer.
 *
 * ### Why the component exists at all, restated so the lift cannot lose it
 *
 * It replaces a sub-card that listed all six terms at equal weight. Most of them are
 * neutral most of the time -- three multiplicands at 1.00 and two penalties at 0.00 is
 * "nothing reduced it", spelled as five rows a reader has to decode. Worse, a neutral
 * value LOOKS different per term: 1.00 is neutral for a multiplicand and total for a
 * penalty, so the card taught the wrong reading of its own numbers.
 *
 * So: name the terms that dragged, say plainly when none did, and keep the informational
 * terms (which are not in the product at all) visually apart.
 *
 * ### It sorts by `kind`, never by term name
 *
 * `MacroConfidenceReason.kind` exists precisely so consumers need not string-match
 * (`models/macro.py:414-418`, `macro/contracts.py:125-134`). §4.1 of the plan is the
 * record of what happens when a producer gets `kind` wrong: `market_path_is_a_shadow`
 * carried `value=0` and inherited the dataclass default `multiplicand`, so the live page
 * printed "market path is a shadow x0.00" beside a confidence of 0.850 -- a term that is
 * not in the product at all, rendered as the thing that destroyed it. A second term,
 * `policy_paths_absent`, carried a COUNT and rendered in NEITHER list. Both are now
 * `informational` at their construction sites, and
 * `tests/unit/macro/test_confidence_term_kinds.py` refolds every engine's terms using
 * `kind` alone and requires the reported confidence back.
 *
 * This component is the web half of that invariant. It must never special-case a term by
 * name: a filter that knew `market_path_is_a_shadow` by string would have passed straight
 * through the bug it exists to catch.
 *
 * ### It does not re-fold the number
 *
 * The confidence itself is the engine's, printed by the caller. Recomputing the product
 * here would put a second arithmetic on screen that could disagree with the one the store
 * holds -- and the desk's whole posture is that a stored answer is replayed, never
 * recomputed at read time.
 *
 * ### The `0` default is carried, not chosen
 *
 * An unparseable `value` folds to 0 -- neutral for a penalty, total drag for a
 * multiplicand. That asymmetry is inherited from the original and is deliberately NOT
 * fixed here, because a lift that changes behaviour is not a lift. It is unreachable
 * today: `MacroConfidenceReason.value` is a required `Decimal`, so the wire always
 * carries a number. If that ever loosens, the honest fix is a fourth lane ("this term did
 * not parse"), not a quieter default.
 */
export function ConfidenceArithmetic({
  reasons,
  testId = "macro-confidence-arithmetic",
}: {
  reasons: MacroConfidenceReason[];
  /** The rates desk's strip has a pinned testid (`tests/unit/rates/StateSection.test.tsx`
   *  asserts it three times), so the lift keeps that contract by passing it in rather
   *  than renaming the assertions. */
  testId?: string;
}) {
  if (!reasons.length) return null;

  const drags = reasons.filter((reason) => {
    const value = toNum(reason.value) ?? 0;
    if (reason.kind === "penalty") return value > 0;
    if (reason.kind === "multiplicand") return value < 1;
    return false;
  });
  const notes = reasons.filter((reason) => reason.kind === "informational");

  return (
    <div className={styles.confidenceStrip} data-testid={testId}>
      {drags.length ? (
        <>
          <span className={styles.confidenceStripLabel}>Reduced by</span>
          {drags.map((reason) => (
            <span key={reason.term} className={styles.confidenceDrag}>
              <strong>{fieldLabel(reason.term)}</strong>
              {reason.kind === "penalty"
                ? ` −${((toNum(reason.value) ?? 0) * 100).toFixed(0)}%`
                : ` ×${(toNum(reason.value) ?? 0).toFixed(2)}`}
              <small>{humanizeText(reason.detail)}</small>
            </span>
          ))}
        </>
      ) : (
        <span className={styles.confidenceStripLabel}>
          Nothing reduced it — every load-bearing input is present, fresh and
          uncontradicted.
        </span>
      )}
      {notes.map((note) => (
        <span key={note.term} className={styles.confidenceNote}>
          <strong>{fieldLabel(note.term)}</strong>
          <small>{humanizeText(note.detail)}</small>
        </span>
      ))}
    </div>
  );
}
