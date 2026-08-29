import type { components } from "@/lib/types";

import { ConfidenceArithmetic } from "../ConfidenceArithmetic";
import { plural } from "../format";
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
 * ### Half of this panel refuses, and that is the shipped state
 *
 * The board draws a probability bar per meeting — hike/hold against cut — sourced from the
 * market-implied lane. On this desk that lane publishes `missing_reason` instead of a
 * path, so there are no probabilities to split a bar with. The panel therefore renders
 * the dated meetings it DOES have, from the lanes that published, and states the refusal
 * in the publisher's own words rather than drawing a bar out of the two lanes that
 * remain. A dealer survey is not a market price and a bar built from one, labelled as the
 * other, would be the panel lying about its own source.
 */
export function FomcCalendarPanel({
  policy,
}: {
  policy: { value: PolicyComparison | null; error?: string };
}) {
  const p = policy.value;
  const dealer = p?.dealer_expectations;
  const committee = p?.committee_projection;
  const marketReason = p?.market_implied?.missing_reason;
  const actualRate = Number(p?.actual?.path?.points?.[0]?.rate_percent);

  /** Dated horizons from whichever lane published them, nearest first. These are meeting
   *  dates and year-ends, which is what the two lanes publish — not our calendar. */
  const meetings = (dealer?.path?.points ?? [])
    .map((pt) => ({
      horizon: pt.horizon,
      date: pt.horizon_date ?? null,
      rate: Number(pt.rate_percent),
    }))
    .filter((m) => m.date && Number.isFinite(m.rate))
    .sort((a, b) => (a.date ?? "").localeCompare(b.date ?? ""))
    .slice(0, 4);

  return (
    <BoardPanel
      id="fomc-calendar"
      title="FOMC calendar × what each lane expects"
      questions={["Q2", "Q6"]}
      basis="REAL"
      source={
        <>
          /api/macro/policy · dealer_expectations horizons (NY Fed SME survey)
          and the committee&rsquo;s SEP · the market-implied lane publishes no
          path on this desk
        </>
      }
    >
      {!p ? (
        <p className="cap">
          {policy.error ??
            "No policy comparison has been assembled for this instant."}
        </p>
      ) : (
        <>
          {meetings.map((m) => {
            const drift = Number.isFinite(actualRate)
              ? m.rate - actualRate
              : null;
            return (
              <div className="meet" key={`${m.horizon}-${m.date}`}>
                <div className="meet-h">
                  <b>{m.horizon}</b>
                  <span className="num">
                    {m.rate.toFixed(3)}%
                    {drift !== null ? (
                      <span
                        className={
                          drift > 0
                            ? "delta-up"
                            : drift < 0
                              ? "delta-dn"
                              : "delta-flat"
                        }
                      >
                        {" "}
                        {drift > 0 ? "+" : drift < 0 ? "−" : "±"}
                        {Math.abs(drift * 100).toFixed(0)}bp vs current
                      </span>
                    ) : null}
                  </span>
                </div>
              </div>
            );
          })}

          {meetings.length === 0 ? (
            <p className="cap">
              No dated horizon was published by any lane, so there is no
              calendar to show.
            </p>
          ) : null}

          <BoardRefusal
            kind="HONEST BOUNDARY"
            testId="macro-market-implied-refusal"
          >
            The board draws a per-meeting probability bar here. This desk
            cannot:{" "}
            {marketReason ?? "the market-implied lane published no path"}. The
            dealer and committee lanes above are expectations, not prices, and a
            bar built from them under a &ldquo;what the market prices&rdquo;
            heading would misname its own source. The bar returns when the lane
            does.
          </BoardRefusal>

          {committee?.path?.release_date ? (
            <p className="cap">
              Committee projection as released {committee.path.release_date};
              dealer survey {dealer?.path?.release_date ?? "undated"}.
            </p>
          ) : null}
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
      title="Confidence repair · which input is holding each domain down"
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
                    <td>{row.binding.term}</td>
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
            No domain that answered is carrying a multiplicand below 1 — nothing
            is currently costing confidence. That is a statement about the terms
            the engines published, not a claim that the evidence is complete.
          </>
        ) : (
          <>
            <b>
              {plural(degraded.length, "domain")} degraded
            </b>{" "}
            by a named term:{" "}
            {degraded
              .map((d) => `${DOMAIN_LABEL[d.domain]} (${d.binding!.term})`)
              .join(", ")}
            . A freshness term is repairable by a release; a completeness term
            is repairable by an ingest. Both are addressable, which is why the
            term is printed rather than only the number it produced.
          </>
        )}
      </BoardRead>
    </BoardPanel>
  );
}
