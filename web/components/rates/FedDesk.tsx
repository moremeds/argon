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
import { PolicySection } from "./sections/PolicySection";
import { StateSection } from "./sections/StateSection";
import type { Policy, PolicyComparison, Snapshot } from "./types";

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
const NAV: readonly NavGroup[] = [
  {
    id: "tier-answer",
    tier: "The answer",
    lede: "What this desk says about policy right now, and how sure it is.",
    items: [["state", "State"]],
  },
  {
    id: "tier-publishers",
    tier: "Who says what",
    lede: "Each publisher on its own axes, and how far it has moved since its last release.",
    items: [
      ["paths", "Four lanes"],
      ["sep-plot", "Dot plot"],
      ["dealer-plot", "Dealer path"],
    ],
  },
  {
    id: "tier-mechanics",
    tier: "Mechanics",
    // The old lede named four panels ("policy settings, issuance, positioning,
    // cross-market"); three of them now live on tab 02 — issuance joined them on
    // 2026-08-28, see the block above `FedDesk` — so the sentence is trimmed to what
    // this tab actually carries rather than kept verbatim and made false.
    lede: "The plumbing a policy view stands on: the policy settings themselves.",
    items: [["policy", "Policy"]],
  },
  {
    id: "tier-provenance",
    tier: "Provenance and legacy",
    // Same trim: the legacy rule score is quarantined on tab 02, so this tab's
    // provenance tier is provenance only.
    lede: "Where the numbers came from, and what this tab will not say.",
    items: [
      ["events", "Events"],
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
}: {
  snapshot: Snapshot | null;
  errorMessage?: string;
  policyComparison?: PolicyComparison | null;
  policyComparisonError?: string;
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

  return (
    <div className={styles.page}>
      <DeskHeader
        title="Fed Policy Desk"
        subtitle="Policy paths and plumbing"
        snapshot={snapshot}
        nav={NAV}
        navLabel="Fed policy sections"
      />

      <RatesTier
        id="tier-answer"
        title="The answer"
        lede="What this desk says about policy right now, and how sure it is."
      />

      <RatesSection
        id="state"
        title="Policy / Rates State"
        eyebrow="Point-in-time evidence"
      >
        <StateSection state={snapshot.state} />
      </RatesSection>

      <RatesTier
        id="tier-publishers"
        title="Who says what"
        lede="Each publisher on its own axes, and how far it has moved since its last release."
      />

      <RatesSection id="paths" title="Policy Paths">
        <PolicyPathComparison
          comparison={policyComparison}
          errorMessage={policyComparisonError}
        />

        {/* The two publishers that plot, inside the same section as the four lanes
            they belong to -- they ARE two of those lanes, and splitting them into
            sibling sections asked the reader to hold that connection themselves.
            Still two blocks with two sets of axes: sharing a frame would draw a
            comparison this desk refuses to make. */}
        <div className={styles.pathPlots}>
          <div id="sep-plot" className={styles.pathPlot}>
            <h3>Committee projection (SEP)</h3>
            <SepDotPlot slot={policyComparison?.committee_projection} />
          </div>
          <div id="dealer-plot" className={styles.pathPlot}>
            <h3>Dealer expectations</h3>
            <DealerPathChart slot={policyComparison?.dealer_expectations} />
          </div>
        </div>
      </RatesSection>

      <RatesTier
        id="tier-mechanics"
        title="Mechanics"
        lede="The plumbing a policy view stands on: the policy settings themselves."
      />

      <RatesSection
        id="policy"
        title="Policy"
        status={statusLabel(policy?.status)}
      >
        <PolicySection policy={policy} />
      </RatesSection>

      <RatesTier
        id="tier-provenance"
        title="Provenance and legacy"
        lede="Where the numbers came from, and what this tab will not say."
      />

      <RatesSection
        id="events"
        title="Events"
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
        <div className={styles.notePanel}>
          <p>
            <strong>No averaging of the four paths.</strong> They are published
            by four different bodies against four different questions.{" "}
            <code>PolicyPathComparison.tsx</code> puts it plainly: a blended
            &ldquo;Fed path&rdquo; would be a number no committee voted on, no
            dealer forecast, and no market traded.
          </p>
          <p>
            <strong>SEP dots stay anonymous.</strong> The FOMC does not publish
            attribution, so neither do we — no dot is ever tied to a named
            official. Hardened rather than intended: unit and e2e tests both
            assert the rendered block never matches <code>/chair|powell/i</code>
            .
          </p>
          <p>
            <strong>A short column is printed short.</strong> When a projection
            year carries fewer participants than the one beside it, the count is
            rendered as published. Normalising it to a full committee would
            invent a projection nobody made.
          </p>
          <p>
            <strong>A survey corroborates only its own window.</strong> Each
            release is plotted against its own release date, so an older survey
            confirms the direction through the day it was taken and says nothing
            about the weeks since. That is why the releases are not merged into
            one line.
          </p>
          <p>
            The curve-side refusals — a slope is not a term premium, and the
            legacy rule scorecard is under quarantine — moved with their
            evidence to the Rates · Curve tab.
          </p>
        </div>
      </RatesSection>

      <SourceFreshnessSection snapshot={snapshot} />
    </div>
  );
}
