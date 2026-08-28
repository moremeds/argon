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
import { SupplySection } from "./sections/SupplySection";
import type { Policy, PolicyComparison, Snapshot, Supply } from "./types";

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
    // cross-market"); two of them now live on tab 02, so the sentence is trimmed to
    // what this tab actually carries rather than kept verbatim and made false.
    lede: "The plumbing a policy view stands on: policy settings and issuance.",
    items: [
      ["policy", "Policy"],
      ["supply", "Supply"],
    ],
  },
  {
    id: "tier-provenance",
    tier: "Provenance and legacy",
    // Same trim: the legacy rule score is quarantined on tab 02, so this tab's
    // provenance tier is provenance only.
    lede: "Where the numbers came from.",
    items: [
      ["events", "Events"],
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
  const supply = snapshot.supply as Supply | undefined;

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
        lede="The plumbing a policy view stands on: policy settings and issuance."
      />

      <RatesSection
        id="policy"
        title="Policy"
        status={statusLabel(policy?.status)}
      >
        <PolicySection policy={policy} />
      </RatesSection>

      <RatesSection
        id="supply"
        title="Supply"
        status={statusLabel(supply?.status)}
      >
        <SupplySection supply={supply} />
      </RatesSection>

      <RatesTier
        id="tier-provenance"
        title="Provenance and legacy"
        lede="Where the numbers came from."
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

      <SourceFreshnessSection snapshot={snapshot} />
    </div>
  );
}
