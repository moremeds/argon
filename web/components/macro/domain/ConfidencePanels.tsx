import { Fragment } from "react";

import { BoardPanel, BoardRead } from "./BoardPanel";
import {
  confidenceChain,
  fmtConfidence,
  repairTable,
  type ChainTerm,
  type ConfidenceChain,
  type ConfidenceReason,
} from "./confidence";

/** A multiplicand prints as itself; a penalty prints as the subtraction it performs, so
 *  the row reads as one continuous product rather than a mix of two conventions. This is
 *  the board's own face: `1.00`, `0.53`, `(1−0.30)`. */
function termFace(t: ChainTerm): string {
  return t.kind === "penalty"
    ? `(1 − ${t.raw.toFixed(2)})`
    : t.factor.toFixed(2);
}

/**
 * The board colours a degraded term's border by WHICH KIND of term degraded it.
 *
 * A multiplicand below 1 is an input that has decayed — freshness, completeness — and
 * warns amber. A penalty that fired is a rule that caught something, and reads as a fault
 * in red. A term at its clear value gets the default border and is still shown: the board
 * prints `(1 − 0.00)` for a penalty that did not fire, because a chain that hid its
 * clean terms would look like a chain of complaints.
 */
function termClass(t: ChainTerm): string {
  if (t.factor >= 1) return "term";
  return t.kind === "penalty" ? "term bad" : "term warn";
}

/**
 * Board t3 · "The arithmetic of confidence · why only 0.37".
 *
 * Every term, including the ones that did not fire, then the product, then a
 * reconciliation against what the engine published. See `confidence.ts` for why the
 * reconciliation is rendered rather than assumed.
 *
 * The `<small>` under each term names the term only, which is where the board lands too
 * ("quality", "completeness 8/8"). Our engine's `detail` strings run to sixty characters
 * where the board's mock uses three words, and at `white-space: nowrap` inside a
 * half-width panel that turns the chain into a scroller showing two terms at a time —
 * which defeats the panel, whose whole point is seeing the product. So every detail is
 * rendered VERBATIM in the read beneath (and on each term's `title`), never abbreviated:
 * the board's rule is that every term names its evidence, not that it does so in the
 * chip. Nothing is dropped to make a layout fit.
 */
export function ConfidenceArithmeticPanel({
  reasons,
  confidence,
  endpoint,
}: {
  reasons: readonly ConfidenceReason[];
  confidence: string | number | null | undefined;
  /** The route the terms came off, named for the footer. */
  endpoint: string;
}) {
  const chain = confidenceChain(reasons, confidence);

  // Terms the engine publishes but does not multiply. They belong on the provenance
  // line, not in the chain: they describe the evidence, they are not factors of it.
  const carried =
    chain.informational.length === 0 ? null : (
      <>
        {" · carried but not multiplied: "}
        {chain.informational
          .map((r) => `${r.term.replace(/_/g, " ")} ${r.value}`)
          .join(", ")}
      </>
    );

  if (chain.terms.length === 0) {
    return (
      <BoardPanel
        id="confidence-arithmetic"
        title="The arithmetic of confidence"
        questions={["Q7"]}
        basis="REAL"
        source={
          <>
            {endpoint} confidence_reasons[]{carried}
          </>
        }
      >
        <BoardRead>
          This state carries no confidence terms, so its number cannot be
          audited here. That is a gap in the engine&apos;s output, not a
          statement that the confidence is unfounded.
        </BoardRead>
      </BoardPanel>
    );
  }

  return (
    <BoardPanel
      id="confidence-arithmetic"
      title={`The arithmetic of confidence · why ${fmtConfidence(chain.reported)}`}
      questions={["Q7"]}
      basis="REAL"
      source={
        <>
          {endpoint} confidence_reasons[] — every term as published, including
          the ones that did not fire{carried}
        </>
      }
    >
      <div className="arith" data-testid="confidence-chain">
        {chain.terms.map((t, i) => (
          <Fragment key={t.term}>
            {i > 0 ? <span className="op">×</span> : null}
            <span className={termClass(t)} title={t.detail}>
              {termFace(t)}
              <small>{t.term.replace(/_/g, " ")}</small>
            </span>
          </Fragment>
        ))}
        {/* The `=` and the product travel as one item so a wrap can never strand the
            operator on the line above its own answer. */}
        <span
          style={{
            display: "flex",
            gap: 5,
            alignItems: "center",
            flex: "0 0 auto",
          }}
        >
          <span className="op">=</span>
          <span className={chain.reconciles ? "res" : "res bad"}>
            conf {fmtConfidence(chain.product)}
          </span>
        </span>
      </div>

      <BoardRead bad={!chain.reconciles} testId="confidence-reconciliation">
        {chain.reconciles ? (
          <>
            The product reproduces the published {fmtConfidence(chain.reported)}{" "}
            digit for digit. Confidence here is{" "}
            <b>auditable multiplication, not a score</b> — every term names the
            evidence that moved it, so a low number is information about the
            inputs rather than a verdict about the world.
          </>
        ) : (
          <>
            These terms multiply to {chain.product.toFixed(4)}, and the engine
            published{" "}
            {chain.reported === null ? "—" : chain.reported.toFixed(4)}.{" "}
            <b>The chain does not reproduce the number</b>, so read neither as
            proof of the other until the engine and this page are reconciled.
          </>
        )}{" "}
        Each term&apos;s evidence, as published:{" "}
        {chain.terms.map((t, i) => (
          <Fragment key={t.term}>
            {i > 0 ? "; " : ""}
            {t.term.replace(/_/g, " ")} — {t.detail}
          </Fragment>
        ))}
        .
      </BoardRead>
    </BoardPanel>
  );
}

/**
 * Board t3 · "Falsifier window · confidence repair table".
 *
 * The board's boundary, kept: only state/confidence sensitivity, which is computable from
 * the terms already on screen. No event probability and no date — this table says what a
 * repair would be worth, never whether or when it arrives. The board tags the release-day
 * threshold question `PLANNED` for exactly that reason, and so does the footer here.
 */
export function ConfidenceRepairPanel({
  reasons,
  confidence,
}: {
  reasons: readonly ConfidenceReason[];
  confidence: string | number | null | undefined;
}) {
  const chain: ConfidenceChain = confidenceChain(reasons, confidence);
  const table = repairTable(chain);

  return (
    <BoardPanel
      id="confidence-repair"
      title="Falsifier window · confidence repair table"
      questions={["Q6"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="the multiplication chain at left, with exactly one term set to its clear value — no probability and no date is estimated here"
    >
      {table.rows.length === 0 ? (
        <BoardRead>
          Every term is already at its clear value, so there is nothing to
          repair — this confidence is not being held down by any input on the
          chain.
        </BoardRead>
      ) : (
        <>
          <div className="tbl-wrap">
            <table data-testid="confidence-repair-table">
              <thead>
                <tr>
                  <th>Event</th>
                  <th className="num">conf consequence</th>
                </tr>
              </thead>
              <tbody>
                {table.rows.map((row) => (
                  <tr key={row.term}>
                    <td>
                      {row.term.replace(/_/g, " ")} clears — {row.detail}
                    </td>
                    <td className="num">
                      {fmtConfidence(table.from)} → {fmtConfidence(row.to)}
                    </td>
                  </tr>
                ))}
                {table.allClear !== null ? (
                  <tr>
                    <td>All clear</td>
                    <td className="num">
                      {fmtConfidence(table.from)} →{" "}
                      {fmtConfidence(table.allClear)}
                    </td>
                  </tr>
                ) : null}
              </tbody>
            </table>
          </div>
          <BoardRead>
            Each row lifts <b>one</b> term to its clear value and leaves the
            rest as published — so a row is what that single repair is worth,
            never a forecast that it happens. The precise release-day threshold
            (what print flips the state label) is not computable from this
            response and is not guessed at here.
          </BoardRead>
        </>
      )}
    </BoardPanel>
  );
}
