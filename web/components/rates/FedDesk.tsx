import { DealerPathChart } from "./DealerPathChart";
import { PolicyPathComparison } from "./PolicyPathComparison";
import styles from "./RatesDesk.module.css";
import { RatesSection } from "./RatesSection";
import { SepDotPlot } from "./SepDotPlot";
import { DeskEmptyState, DeskHeader } from "./deskShared";
import { MarketImpliedOddsSection } from "./sections/MarketImpliedOddsSection";
import { PolicySection } from "./sections/PolicySection";
import { StateSection } from "./sections/StateSection";
import type {
  MacroStateSummary,
  Policy,
  PolicyComparison,
  Snapshot,
} from "./types";
import type { components } from "@/lib/types";

type MacroDomainState = components["schemas"]["MacroDomainStateResponse"];

/** The router's own constant for where the state detail lives (`routers/rates.py`). */
const STATE_DETAIL_PATH = "/api/macro/rates";

function firstPathRate(
  slot:
    | { path?: { points?: { rate_percent: string | number }[] } | null }
    | null
    | undefined,
): string {
  const value = Number(slot?.path?.points?.[0]?.rate_percent);
  return Number.isFinite(value) ? value.toFixed(2) : "unavailable";
}

/**
 * Macro desk tab 01 — Fed · Policy.
 *
 * One of the two halves the old `/rates` page (`RatesDesk.tsx`, 602 L) split into. This
 * one answers "what is the Fed doing, who says so, and what plumbing is that standing
 * on". The traded curve and everything derived from it lives on tab 02, `CurveDesk`.
 *
 * The split is by question, not by convenience: a reader arriving after a rate decision
 * wants the state, the four published paths, and the settings underneath them. Making
 * him scroll past a yield-curve chart to reach the dot plot was the old page's ordering,
 * and it ordered by nothing.
 *
 * ### Two corrections made on 2026-08-28, both from the board
 *
 * **Issuance moved to tab 02.** The board puts `Supply SUB-STATE` and `Auction demand`
 * on Rates · Curve, and `SupplySection` renders both. It landed here because the old
 * `/rates` page had it under a "Mechanics" heading this tab inherited wholesale — which
 * is an argument about where it used to sit, not about which question it answers. It
 * answers who is issuing and who showed up to buy, and that is a curve question.
 *
 * **This tab now states its refusals.** It was the only one of the five shipping without
 * a refusal panel, which mattered more here than anywhere: this is the tab carrying four
 * separate published paths that a reader will want to average.
 */
export function FedDesk({
  snapshot,
  errorMessage,
  policyComparison,
  policyComparisonError,
  ratesState,
}: {
  snapshot: Snapshot | null;
  errorMessage?: string;
  policyComparison?: PolicyComparison | null;
  policyComparisonError?: string;
  /**
   * `/api/macro/rates`, cited as the FALLBACK source for the state panel.
   *
   * `RatesSnapshotResponse.state` is gated behind `settings.rates_snapshot_state_block_
   * enabled`, which defaults FALSE (`config.py`). With it off the snapshot returns
   * `state: null` and the board's "State & confidence · the engine's own proof" panel had
   * nothing to prove anything with — a board panel permanently empty by configuration
   * rather than by fact.
   *
   * The board names this exact route for that case: "if that flag is off the same state
   * is still reachable via `/api/macro/rates`". Preferring the snapshot's own block when
   * present keeps the single-fetch design the page argues for; the citation only fills a
   * hole, and cannot fork an answer that is not there to fork.
   */
  ratesState?: MacroDomainState | null;
}) {
  if (!snapshot) {
    return (
      <DeskEmptyState eyebrow="Fed Policy Desk" errorMessage={errorMessage} />
    );
  }

  const policy: Policy = snapshot.policy ?? {
    status: "partial",
    plumbing: [],
    implied_path: [],
  };

  // `MacroDomainStateResponse` is a superset of `MacroStateSummary` but for two fields:
  // it carries the evidence ROWS where the summary carries their count, and it has no
  // `detail_path` because it IS the detail. Both are derived rather than defaulted, so
  // the panel cannot claim an evidence count it did not get.
  const stateSummary: MacroStateSummary | null =
    snapshot.state ??
    (ratesState
      ? {
          ...ratesState,
          evidence_count: ratesState.evidence?.length ?? 0,
          detail_path: STATE_DETAIL_PATH,
        }
      : null);

  return (
    <div className={styles.page}>
      <div className="board">
        {/* The board's own t1 heading, question strip and standfirst. The strip is the
          board's `Q1 Q2 Q3 Q5 Q7` verbatim; the standfirst keeps the two sentences that
          describe the DESK and drops the board's opening clause about the merge itself
          ("5 tiers, 18 sections … deduplication, not new construction"), which is
          reviewer-facing prose about the port rather than something an operator reading
          the Fed tab needs. */}
        <DeskHeader
          title="Fed · Policy"
          questions={["Q1", "Q2", "Q3", "Q5", "Q7"]}
          showState
          standfirst={
            <>
              This tab answers <b>what the committee intends</b>; the term
              structure it produces lives next door in <b>02 Rates · Curve</b>.
              The spine of this tab:{" "}
              <b>four policy paths shown separately, never averaged</b> — a
              blended &ldquo;Fed path&rdquo; would be a number no committee
              voted on, no dealer forecast, and no market traded.
            </>
          }
          snapshot={snapshot}
        />

        {/* The board's t1 is a sequence of `grid g2` rows, not a column of full-width
          sections — which is why the board/live pixel compare measured this tab 41%
          taller than its own spec for the same content. The pairings are the board's. */}
        <div className="grid g2">
          <RatesSection
            id="paths"
            title="Four policy paths · who says what"
            questions={["Q2"]}
            basis="REAL"
            source="/api/macro/policy · four publisher lanes, never averaged"
          >
            <PolicyPathComparison
              comparison={policyComparison}
              errorMessage={policyComparisonError}
            />
          </RatesSection>

          {/* The board gives the market-implied lane its own panel and this tab shipped
            without one. `market_implied` is a three-state slot currently in its third
            state, and an absent panel says "this desk does not cover market-implied odds"
            where the truth is "it does, and the publisher had nothing" -- see the component
            for why that distinction is load-bearing on exactly this lane. */}
          <RatesSection
            id="market-implied"
            title="Per-meeting odds · market-implied"
            eyebrow="The only lane a market actually traded"
            questions={["Q2", "Q6"]}
            basis="REAL"
            source="/api/macro/policy · market_implied"
          >
            <MarketImpliedOddsSection slot={policyComparison?.market_implied} />
          </RatesSection>
        </div>

        {/* Two publishers, two full-width panels, two sets of axes. */}
          {/* Two publishers, two panels, two sets of axes. They were one section holding
            both plots; the board separates them, and the separation is the point -- a
            shared frame would draw the comparison this desk refuses to make. */}
          <RatesSection
            id="dealer-plot"
            title={`Dealer expectations · the ${firstPathRate(policyComparison?.dealer_expectations)} dot, unrolled`}
            eyebrow="Primary-dealer survey · each release against its own date"
            questions={["Q2", "Q3", "Q6"]}
            basis="REAL"
            source="/api/macro/policy · dealer_expectations"
          >
            <DealerPathChart slot={policyComparison?.dealer_expectations} />
          </RatesSection>

          <RatesSection
            id="sep-plot"
            title={`Committee projections · the ${firstPathRate(policyComparison?.committee_projection)} dot, unrolled`}
            eyebrow="FOMC SEP · dots stay anonymous"
            questions={["Q1", "Q3"]}
            basis="REAL"
            source="/api/macro/policy · committee_projection"
          >
            <SepDotPlot slot={policyComparison?.committee_projection} />
          </RatesSection>

        {/* The board puts the state AFTER the publishers, not before, and it is right to:
          the state is a reading OF those four lanes, and printing it first invites it to
          be read as a fifth opinion rather than a verdict on the other four. */}
        <div className="grid g2">
          <RatesSection
          id="state"
          title="State & confidence · the engine's own proof"
          eyebrow="Point-in-time evidence"
          questions={["Q1", "Q7"]}
          basis="COMPUTED"
          source="/api/rates/snapshot.state; fallback /api/macro/rates"
        >
          <StateSection state={stateSummary} />
          </RatesSection>

          <RatesSection
          id="policy"
          title="Plumbing · the balance sheet behind the rate"
          questions={["Q4"]}
          basis="REAL"
          source="/api/rates/snapshot.policy"
        >
          <PolicySection policy={policy} />
          </RatesSection>
        </div>

        <div className="grid g2">
          <RatesSection
            id="events"
            title="Next events"
            questions={["Q6"]}
            basis="REAL"
            source="/api/rates/snapshot.events"
          >
            {snapshot.events?.length ? (
              <div className="tbl-wrap">
                <table>
                  <thead>
                    <tr>
                      <th>Date</th>
                      <th>Event</th>
                      <th>What it can move</th>
                    </tr>
                  </thead>
                  <tbody>
                    {snapshot.events.map((event) => (
                      <tr key={`${event.event_date}-${event.label}`}>
                        <td className="num">{event.event_date ?? "—"}</td>
                        <td>{event.label}</td>
                        <td>{event.source ?? `${event.importance} importance`}</td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            ) : (
              <p className="read">Official events/news source not wired in Phase 1.</p>
            )}
          </RatesSection>

          {/* The board gives every tab one of these and this tab shipped without it — the
          only one of the five that did. Each bullet is an invariant that already exists
          somewhere in `components/rates/*`, stated here so a reader meets it before he
          reads a chart that depends on it, rather than only in a code comment he will
          never open. Every claim names where it is enforced; none of them restates a
          number, because a refusal that goes stale is worse than no refusal. */}
          <RatesSection
            id="refuses"
            title="What this tab refuses"
            questions={["Q7"]}
            basis="REAL"
            source="code invariants and executable tests"
          >
            <ul className="tight">
              <li>
                <b>No averaging of the four paths.</b> They are
                published by four different bodies against four different
                questions. <code>PolicyPathComparison.tsx</code> puts it
                plainly: a blended &ldquo;Fed path&rdquo; would be a number no
                committee voted on, no dealer forecast, and no market traded.
              </li>
              <li>
                <b>SEP dots stay anonymous.</b> The FOMC does not
                publish attribution, so neither do we — no dot is ever tied to a
                named official. Hardened rather than intended: unit and e2e
                tests both assert the rendered block never matches{" "}
                <code>/chair|powell/i</code>.
              </li>
              <li>
                <b>A short column is printed short.</b> When a
                projection year carries fewer participants than the one beside
                it, the count is rendered as published. Normalising it to a full
                committee would invent a projection nobody made.
              </li>
              <li>
                <b>A survey corroborates only its own window.</b> Each
                release is plotted against its own release date, so an older
                survey confirms the direction through the day it was taken and
                says nothing about the weeks since. That is why the releases are
                not merged into one line.
              </li>
            </ul>
            <p className="cap">
                The curve-side refusals — a slope is not a term premium, and the
                legacy rule scorecard is under quarantine — moved with their
                evidence to the Rates · Curve tab.
            </p>
          </RatesSection>
        </div>
      </div>
    </div>
  );
}
