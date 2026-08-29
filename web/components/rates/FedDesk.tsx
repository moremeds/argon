import { DealerPathChart } from "./DealerPathChart";
import { PolicyPathComparison } from "./PolicyPathComparison";
import styles from "./RatesDesk.module.css";
import { RatesSection, RatesTier } from "./RatesSection";
import { SepDotPlot } from "./SepDotPlot";
import {
  DeskEmptyState,
  DeskHeader,
  SourceFreshnessSection,
  type NavGroup,
} from "./deskShared";
import { statusLabel } from "./format";
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
// NAV order follows DOCUMENT order, and both changed on 2026-08-29. The board puts the
// four publishers first and the state after them: the state is a reading OF those lanes,
// and printing it first invites it to be read as a fifth opinion rather than a verdict on
// the other four.
const NAV: readonly NavGroup[] = [
  {
    id: "tier-publishers",
    tier: "Who says what",
    lede: "Each publisher on its own axes, and how far it has moved since its last release.",
    items: [
      ["paths", "Four lanes"],
      ["market-implied", "Per-meeting odds"],
      ["dealer-plot", "Dealer path"],
      ["sep-plot", "Dot plot"],
    ],
  },
  {
    id: "tier-answer",
    tier: "The answer",
    lede: "What this desk says about policy right now, and how sure it is.",
    items: [["state", "State & confidence"]],
  },
  {
    id: "tier-mechanics",
    tier: "Mechanics",
    // The old lede named four panels ("policy settings, issuance, positioning,
    // cross-market"); three of them now live on tab 02 — issuance joined them on
    // 2026-08-28, see the block above `FedDesk` — so the sentence is trimmed to what
    // this tab actually carries rather than kept verbatim and made false.
    lede: "The plumbing a policy view stands on: the policy settings themselves.",
    items: [["policy", "Plumbing"]],
  },
  {
    id: "tier-provenance",
    tier: "Provenance and legacy",
    // Same trim: the legacy rule score is quarantined on tab 02, so this tab's
    // provenance tier is provenance only.
    lede: "Where the numbers came from, and what this tab will not say.",
    items: [
      ["events", "Next events"],
      ["refuses", "Refusals"],
      ["sources", "Sources"],
    ],
  },
];

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
          nav={NAV}
          navLabel="Fed policy sections"
        />

        <RatesTier
          id="tier-publishers"
          title="Who says what"
          lede="Each publisher on its own axes, and how far it has moved since its last release."
        />

        {/* The board's t1 is a sequence of `grid g2` rows, not a column of full-width
          sections — which is why the board/live pixel compare measured this tab 41%
          taller than its own spec for the same content. The pairings are the board's. */}
        <div className="grid g2">
          <RatesSection id="paths" title="Four policy paths · who says what">
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
          >
            <MarketImpliedOddsSection slot={policyComparison?.market_implied} />
          </RatesSection>
        </div>

        <div className="grid g2">
          {/* Two publishers, two panels, two sets of axes. They were one section holding
            both plots; the board separates them, and the separation is the point -- a
            shared frame would draw the comparison this desk refuses to make. */}
          <RatesSection
            id="dealer-plot"
            title="Dealer expectations · unrolled"
            eyebrow="Primary-dealer survey · each release against its own date"
          >
            <DealerPathChart slot={policyComparison?.dealer_expectations} />
          </RatesSection>

          <RatesSection
            id="sep-plot"
            title="Committee projections · unrolled"
            eyebrow="FOMC SEP · dots stay anonymous"
          >
            <SepDotPlot slot={policyComparison?.committee_projection} />
          </RatesSection>
        </div>

        <RatesTier
          id="tier-answer"
          title="The answer"
          lede="What this desk says about policy right now, and how sure it is."
        />

        {/* The board puts the state AFTER the publishers, not before, and it is right to:
          the state is a reading OF those four lanes, and printing it first invites it to
          be read as a fifth opinion rather than a verdict on the other four. */}
        <RatesSection
          id="state"
          title="State & confidence · the engine's own proof"
          eyebrow="Point-in-time evidence"
        >
          <StateSection state={stateSummary} />
        </RatesSection>

        <RatesTier
          id="tier-mechanics"
          title="Mechanics"
          lede="The plumbing a policy view stands on: the policy settings themselves."
        />

        <RatesSection
          id="policy"
          title="Plumbing · the balance sheet behind the rate"
          status={statusLabel(policy?.status)}
        >
          <PolicySection policy={policy} />
        </RatesSection>

        <RatesTier
          id="tier-provenance"
          title="Provenance and legacy"
          lede="Where the numbers came from, and what this tab will not say."
        />

        <div className="grid g2">
          <RatesSection
            id="events"
            title="Next events"
            status={snapshot.events?.length ? "Live" : "Unavailable"}
          >
            <div className={styles.notePanel}>
              {snapshot.events?.length ? (
                snapshot.events.map((event) => (
                  <p key={event.label}>{event.label}</p>
                ))
              ) : (
                <p>Official events/news source not wired in Phase 1.</p>
              )}
            </div>
          </RatesSection>

          {/* The board gives every tab one of these and this tab shipped without it — the
          only one of the five that did. Each bullet is an invariant that already exists
          somewhere in `components/rates/*`, stated here so a reader meets it before he
          reads a chart that depends on it, rather than only in a code comment he will
          never open. Every claim names where it is enforced; none of them restates a
          number, because a refusal that goes stale is worse than no refusal. */}
          <RatesSection id="refuses" title="What this tab refuses">
            <div className={`${styles.notePanel} ${styles.noteRefuse}`}>
              <p>
                <strong>No averaging of the four paths.</strong> They are
                published by four different bodies against four different
                questions. <code>PolicyPathComparison.tsx</code> puts it
                plainly: a blended &ldquo;Fed path&rdquo; would be a number no
                committee voted on, no dealer forecast, and no market traded.
              </p>
              <p>
                <strong>SEP dots stay anonymous.</strong> The FOMC does not
                publish attribution, so neither do we — no dot is ever tied to a
                named official. Hardened rather than intended: unit and e2e
                tests both assert the rendered block never matches{" "}
                <code>/chair|powell/i</code>.
              </p>
              <p>
                <strong>A short column is printed short.</strong> When a
                projection year carries fewer participants than the one beside
                it, the count is rendered as published. Normalising it to a full
                committee would invent a projection nobody made.
              </p>
              <p>
                <strong>A survey corroborates only its own window.</strong> Each
                release is plotted against its own release date, so an older
                survey confirms the direction through the day it was taken and
                says nothing about the weeks since. That is why the releases are
                not merged into one line.
              </p>
              <p>
                The curve-side refusals — a slope is not a term premium, and the
                legacy rule scorecard is under quarantine — moved with their
                evidence to the Rates · Curve tab.
              </p>
            </div>
          </RatesSection>
        </div>

        <SourceFreshnessSection snapshot={snapshot} />
      </div>
    </div>
  );
}
