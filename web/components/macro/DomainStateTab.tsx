import { BoardRefusal, BoardStatePill } from "./domain/BoardPanel";
import type { MacroFactor } from "./domain/FactorTable";
import { InflationPanels } from "./domain/InflationPanels";
import { UsdPanels } from "./domain/UsdPanels";
import type {
  MacroDomainKey,
  MacroDomainSlot,
  MacroDomainState,
} from "./types";
import { DOMAIN_LABEL, DOMAIN_LEDE } from "./types";

/**
 * The board's tab-level question tags: the union of the questions its panels answer.
 *
 * Written down rather than collected from the children, because the panels are opaque
 * `ReactNode`s by the time they reach here. It is not unchecked — every panel carries its
 * own `data-questions`, and `macroDomainStateTab.test.tsx` recomputes the union from the
 * rendered DOM and fails if this disagrees. So the strip cannot drift into advertising a
 * question no panel on the tab actually answers.
 */
const TAB_QUESTIONS: Partial<Record<MacroDomainKey, string>> = {
  inflation: "Q1 Q3 Q6 Q7",
  usd: "Q1 Q4 Q7",
};

/** The stalest load-bearing input, for the sub-title's derived clause. */
function stalest(state: MacroDomainState): MacroFactor | null {
  const factors = (state.factors ?? []) as MacroFactor[];
  if (factors.length === 0) return null;
  return factors.reduce((a, b) => (b.age_days > a.age_days ? b : a));
}

/**
 * One macro domain, as a whole tab, in the board's grammar.
 *
 * ### What this used to be, and why it changed — twice
 *
 * The first version was the shared `DomainStateCard` and nothing else, because §1 of the
 * port plan said tabs 00–05 were a _presentation merge_ with no new analytics. That line
 * was superseded on 2026-08-28: the board specifies FOUR panels for inflation and TWO for
 * the dollar, and a conformance audit found zero of the six on the shipped desk
 * (`docs/research/2026-08-28-macro-desk-board-conformance/`).
 *
 * The second version added those six panels but kept argon's own typography and kept the
 * summary card above them. That was still not the board: the board binds its DESIGN as
 * well as its information, and its t3/t4 have no summary card at all — the `.sec-title`
 * state pill IS the summary, and the `.sec-sub` beneath it names, in prose, exactly what
 * the card's contradiction and freshness rows carried. So the card is gone from the TAB
 * (it stays on `/macro`, the overview it was built for) and its two facts are derived
 * into the sub-title, which is where the board puts them.
 *
 * What did NOT change across either revision is where the numbers come from. The panels
 * add no endpoint and no derived quantity the engine does not publish — the audit's own
 * finding was that the single response each tab already fetched carried every panel. The
 * one arithmetic on this page is the confidence repair table, which is the published
 * multiplication with one published term set to its clear value, tagged `COMPUTED` and
 * showing its formula.
 *
 * The one exception to "one request" is inflation's expectations panel, which cites the
 * rates domain's published breakeven. The board marks that row "(single owner)" for the
 * same reason this cites rather than recomputes it.
 *
 * **The empty slot stays three-state.** §9 invariant 2: `_domain_state` 404s rather than
 * recomputing, and `allow404` turns that into a null value — a fact about the pipeline.
 * An unreachable API is a different fact. Neither may render as the other, and neither
 * renders as a state.
 *
 * **The refusal stays, and still earns its place.** A domain on its own page invites two
 * readings the desk does not support — that the number is a verdict about markets, and
 * that it can be put beside the other three and averaged. §9 invariant 1 forbids the
 * second anywhere in the desk's own chrome, and the chain-level claim already has exactly
 * one home: `/api/macro/snapshot`, which is asserted, tested and stored with an explicit
 * ordinal. A tab that quietly implied it would be a second, unversioned copy of that
 * claim.
 */
export function DomainStateTab({
  domain,
  slot,
  citedRates = null,
  citationError,
}: {
  domain: MacroDomainKey;
  slot: MacroDomainSlot;
  /** The rates domain's published state, for tab 03's market-implied leg. */
  citedRates?: MacroDomainState | null;
  citationError?: string;
}) {
  const state = slot.value;
  const questions = TAB_QUESTIONS[domain];

  return (
    <div className="board" data-testid={`macro-domain-tab-${domain}`}>
      <div className="sec-title">
        <h1>{DOMAIN_LABEL[domain]}</h1>
        {questions ? <span className="tag q">{questions}</span> : null}
        <StatePill domain={domain} slot={slot} />
      </div>

      <p className="sec-sub">
        {DOMAIN_LEDE[domain]} One point-in-time state, replayed from the store
        rather than recomputed at read time, carrying the exact observations it
        stood on.{state ? <DerivedRead state={state} /> : null}
      </p>

      {state && domain === "inflation" ? (
        <InflationPanels
          state={state}
          citedRates={citedRates}
          citationError={citationError}
        />
      ) : null}
      {state && domain === "usd" ? <UsdPanels state={state} /> : null}

      <section
        id="refuses"
        data-testid={`macro-domain-refuses-${domain}`}
        aria-label="What this tab refuses"
        style={{ marginTop: 12 }}
      >
        <BoardRefusal>
          <ul>
            <li>
              It is descriptive. The state is what the engine recorded, not
              advice, and it carries no score, allocation or probability of its
              own.
            </li>
            <li>
              It does not combine this domain with the other three. Whether the
              four belong together is a separate, stored claim — the chain
              verdict on the overview — and averaging four differently-grounded
              answers would hide the contradictions rather than resolve them.
            </li>
            <li>
              The tab order on this desk is a reading order, not a causal one.
              Nothing here says this domain causes the next tab.
            </li>
          </ul>
        </BoardRefusal>
      </section>
    </div>
  );
}

/**
 * The board's state pill, and the three-state empty slot it has to carry.
 *
 * A missing state is not a state, so it never wears a state pill's colour. The two
 * silences are distinguished in the pill's own words: an engine that has not run, and an
 * API that could not be reached. The second also prints the error, because "we could not
 * ask" is only useful with the reason attached.
 */
function StatePill({
  domain,
  slot,
}: {
  domain: MacroDomainKey;
  slot: MacroDomainSlot;
}) {
  return (
    <BoardStatePill
      facts={slot.value}
      testId={`macro-domain-${domain}`}
      absent={
        slot.error ?? "no state — the engine has not run for this instant"
      }
    />
  );
}

/**
 * The board's own derived clause: what the confidence number cost, in facts.
 *
 * The board writes it as prose ("two contradiction rules are firing and one expectations
 * input is 60 days stale") and every part of it is on the response, so it is computed
 * rather than copied — the board's own figures were frozen at its capture instant.
 * Rendered only when there is something to say; a clean state gets the lede alone rather
 * than a sentence announcing that nothing is wrong.
 */
function DerivedRead({ state }: { state: MacroDomainState }) {
  const rules = state.contradictions ?? [];
  const old = stalest(state);
  if (rules.length === 0 && !old) return null;

  const conf = Number(state.confidence);
  return (
    <>
      {" "}
      The label says <b>{state.state}</b>
      {Number.isFinite(conf) ? <> at confidence {conf.toFixed(2)}</> : null}
      {rules.length > 0 ? (
        <>
          {" "}
          — {rules.length} contradiction rule{rules.length === 1 ? "" : "s"}{" "}
          firing ({rules.map((r) => r.rule).join(", ")})
        </>
      ) : null}
      {old ? (
        <>
          {rules.length > 0 ? " and" : " —"} the stalest load-bearing input is{" "}
          {old.series_id} at {old.age_days}d
        </>
      ) : null}
      .{" "}
      {/* Branch on the number rather than asserting the interesting case. A tab whose
          confidence is 1.00 reading "a confidence below 1 is not a defect" describes a
          different state than the one on screen, and the sentence must not point at an
          arithmetic panel that this domain's board section does not have. */}
      {Number.isFinite(conf) && conf < 1 ? (
        <>
          A confidence below 1 is not a defect; it is what those facts cost, and
          the terms that charged them are published with the state.
        </>
      ) : (
        <>Nothing on this state&apos;s evidence is currently discounting it.</>
      )}
    </>
  );
}
