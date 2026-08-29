import type { components } from "@/lib/types";

import { ConfidenceArithmetic } from "../ConfidenceArithmetic";
import { MarketImpliedMeetingBars } from "../MarketImpliedMeetingBars";
import { plural } from "../format";
import { fieldLabel, humanizeIdentifier } from "../presentation";
import { BoardPanel, BoardRead, BoardRefusal } from "../domain/BoardPanel";
import type {
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "../types";

/**
 * ZONE 3 · WHAT'S NEXT — the board's two forward-looking panels.
 *
 * The board's kicker is "dated events that confirm or falsify", and that is the test both
 * panels have to pass: everything here must be a DATE, not a forecast. Neither panel
 * predicts anything. The first says when the committee next meets and what each lane
 * expects by then; the second says which stored input is ageing and what release repairs
 * it. Both are calendar facts about the desk's own evidence.
 */

type PolicyComparison = components["schemas"]["PolicyComparison"];

/**
 * PANEL 8 · FOMC calendar × what the market prices.
 *
 * ### The panel follows the market-implied publisher's three states
 *
 * The board draws one probability bar per meeting from `market_implied.path.points`.
 * Frenzy now supplies that path, so this panel shares Fed's renderer. If the path is
 * absent, the publisher's reason remains visible; dealer and committee expectations are
 * never substituted under a market-pricing heading.
 */
export function FomcCalendarPanel({
  policy,
}: {
  policy: { value: PolicyComparison | null; error?: string };
}) {
  const p = policy.value;
  const marketSlot = p?.market_implied;
  const marketPoints = marketSlot?.path?.points ?? [];
  const marketReason = marketSlot?.missing_reason;
  const marketSource = marketSlot?.path?.source ?? "market-implied publisher";

  return (
    <BoardPanel
      id="fomc-calendar"
      title="FOMC odds"
      questions={["Q2", "Q6"]}
      basis="REAL"
      source={
        marketPoints.length > 0 ? (
          <>
            /api/macro/policy · market_implied.path.points · {marketSource}
          </>
        ) : (
          <>/api/macro/policy · market_implied.missing_reason</>
        )
      }
    >
      {!p ? (
        <p className="cap">
          {policy.error ??
            "No policy comparison has been assembled for this instant."}
        </p>
      ) : (
        <>
          {marketPoints.length > 0 ? (
            <>
              <MarketImpliedMeetingBars points={marketPoints} />
              <BoardRead>Publisher probabilities by meeting; no synthetic distribution.</BoardRead>
              {marketSlot?.path?.release_date ? (
                <p className="cap">
                  Released {marketSlot.path.release_date} by {humanizeIdentifier(marketSource)}.
                </p>
              ) : null}
            </>
          ) : (
            <BoardRefusal
              kind="HONEST BOUNDARY"
              testId="macro-market-implied-refusal"
            >
              {marketReason ?? "The market-pricing lane published no path"}.
              Dealer and Fed projections are not substituted.
            </BoardRefusal>
          )}
        </>
      )}
    </BoardPanel>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * PANEL 9 · Confidence repair
 * ──────────────────────────────────────────────────────────────────────────── */

/**
 * PANEL 9 · Confidence repair · what each event fixes.
 *
 * ### Why a decayed confidence is a dated event and not a warning
 *
 * `confidence_reasons` carries a `freshness` multiplicand whose `detail` names the
 * STALEST load-bearing input and its age ("stalest input MICH at 56d"). That makes the
 * decay addressable: it is not that the domain is less true, it is that one named series
 * has not published. The repair is that series' next release, which is a date.
 *
 * So this panel reads the engine's own terms and reports which input is holding each
 * domain's confidence down. It computes no forecast of the repair and asserts no release
 * calendar the desk does not hold — naming the input is the deliverable, because that is
 * what turns a number going down into something an operator can act on.
 */
export function ConfidenceRepairPanel({
  domains,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
}) {
  const rows = CAUSAL_ORDER.map((domain) => {
    const state = domains[domain].value;
    const reasons = state?.confidence_reasons ?? [];
    // The binding term is the multiplicand furthest below 1 — the one actually costing
    // the domain confidence. Read by `kind`, never by term name: `ConfidenceArithmetic`
    // documents why, and the contract allows terms this desk has not seen.
    const multiplicands = reasons
      .filter((r) => r.kind === "multiplicand")
      .map((r) => ({ ...r, num: Number(r.value) }))
      .filter((r) => Number.isFinite(r.num));
    const binding =
      multiplicands.length > 0
        ? multiplicands.reduce((a, b) => (b.num < a.num ? b : a))
        : null;
    return {
      domain,
      state,
      binding,
      penalties: reasons.filter((r) => r.kind !== "multiplicand"),
    };
  });

  const degraded = rows.filter((r) => r.binding && r.binding.num < 1);

  return (
    <BoardPanel
      id="confidence-repair"
      title="Confidence repair"
      questions={["Q6", "Q7"]}
      basis="REAL"
      source={
        <>
          /api/macro/&#123;domain&#125; confidence_reasons[] · the binding term
          is the multiplicand furthest below 1, read by kind rather than by term
          name
        </>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Domain</th>
              <th>Binding term</th>
              <th className="num">Value</th>
              <th>What it names</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.domain} data-testid={`macro-repair-${row.domain}`}>
                <td>{DOMAIN_LABEL[row.domain]}</td>
                {row.binding ? (
                  <>
                    <td title={row.binding.term} data-raw-value={row.binding.term}>
                      {fieldLabel(row.binding.term)}
                    </td>
                    <td
                      className={`num ${row.binding.num < 1 ? "delta-dn" : "delta-flat"}`}
                    >
                      {row.binding.num.toFixed(3)}
                    </td>
                    <td>{row.binding.detail}</td>
                  </>
                ) : (
                  <td colSpan={3} style={{ color: "var(--text-muted)" }}>
                    {row.state
                      ? "this state published no confidence terms"
                      : "no state at this instant, so no terms to read"}
                  </td>
                )}
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      {/* The full arithmetic per domain, under the summary table.
       *
       * The binding term above answers "what is holding this domain down"; the strip
       * answers "what else is in the product, and what is not in it at all". Both are
       * needed and neither substitutes: the strip's whole reason for existing is that it
       * keeps the INFORMATIONAL terms visually apart from the drags, because those are not
       * multiplied in and listing them together teaches the wrong reading of the numbers.
       *
       * It is the strip that used to be private to the rates page, which meant the rates
       * state was the only one of four whose confidence a reader could argue with. All
       * four render it here. */}
      {rows
        .filter((row) => (row.state?.confidence_reasons ?? []).length > 0)
        .map((row) => (
          <div key={`arith-${row.domain}`}>
            <p className="cap">{DOMAIN_LABEL[row.domain]}</p>
            <ConfidenceArithmetic
              reasons={row.state?.confidence_reasons ?? []}
              testId={`macro-confidence-${row.domain}`}
            />
          </div>
        ))}

      <BoardRead testId="macro-repair-read">
        {degraded.length === 0 ? (
          <>
            No published confidence factor is below 1.
          </>
        ) : (
          <>
            <b>
              {plural(degraded.length, "domain")} degraded
            </b>{" "}
            by a named term:{" "}
            {degraded
              .map((d) => `${DOMAIN_LABEL[d.domain]} (${fieldLabel(d.binding!.term)})`)
              .join(", ")}
            . Freshness needs a release; completeness needs an ingest.
          </>
        )}
      </BoardRead>
    </BoardPanel>
  );
}
