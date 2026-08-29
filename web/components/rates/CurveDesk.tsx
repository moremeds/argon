import type { components } from "@/lib/types";

import { RatesCurveChart } from "./RatesCurveChart";
import styles from "./RatesDesk.module.css";
import { RatesScorecard } from "./RatesScorecard";
import { RatesSection, RatesTier } from "./RatesSection";
import {
  DeskEmptyState,
  DeskHeader,
  SourceFreshnessSection,
  Tile,
  type NavGroup,
} from "./deskShared";
import { fmtValue, statusLabel } from "./format";
import {
  ClevelandDecompositionSection,
  MoveAttributionSection,
  NominalDecompositionSection,
} from "./sections/DecompositionSection";
import { PositioningSection } from "./sections/PositioningSection";
import { SubStateSection } from "./sections/SubStateSection";
import {
  AuctionDemandSection,
  SupplyFiscalSection,
} from "./sections/SupplySection";
import type {
  Decomposition,
  Policy,
  Positioning,
  SlopeMetric,
  Snapshot,
  Supply,
} from "./types";

/**
 * Macro desk tab 02 — Rates · Curve.
 *
 * The market's half of the old `/rates` page: what the traded curve prices, what moved
 * it, and the positioning and cross-market plumbing that stands beside it. The Fed's own
 * state and the four published policy paths live on tab 01, `FedDesk`.
 *
 * `/rates` 308s here rather than to tab 01 (`next.config.mjs`). That used to be the reason
 * this tab kept the old page's "US Rates Factor Desk" lockup — an inbound link should land
 * somewhere that still says its name. The board settled it the other way on 2026-08-28:
 * its t2 opens with `Rates · Curve` and nothing above it, and the tab bar one line up
 * already says the same words, so the lockup was the page announcing itself twice. The
 * old name survives where it is still load-bearing: `DeskEmptyState`'s eyebrow, which is
 * what an inbound link reaches when there is no snapshot to show.
 */
const NAV: readonly NavGroup[] = [
  {
    id: "tier-market",
    tier: "What the market prices",
    lede: "The traded curve, its slopes, and what moved them.",
    items: [
      ["summary", "Summary"],
      ["curve", "Curve"],
      ["decomp", "Nominal decomposition"],
      ["decomp-cleveland", "Cleveland 5-term"],
      ["decomp-attribution", "Move attribution"],
    ],
  },
  {
    id: "tier-mechanics",
    tier: "Mechanics",
    // The old lede named four panels ("policy settings, issuance, positioning,
    // cross-market"); policy settings live on tab 01, and issuance came BACK here on
    // 2026-08-28 because the board puts supply and auction demand on this tab. So the
    // sentence names what this tab actually carries rather than staying verbatim.
    lede: "The plumbing a rates view stands on: issuance, positioning and cross-market.",
    items: [
      ["substate-supply", "Supply"],
      ["substate-positioning", "Positioning"],
      ["substate-plumbing", "Funding"],
      ["auctions", "Auction demand"],
      ["cross", "Cross-market"],
    ],
  },
  {
    id: "tier-provenance",
    tier: "Provenance and legacy",
    lede: "Where the numbers came from, and the older rule score kept for comparison only.",
    items: [
      ["refuses", "Refusals"],
      ["sources", "Sources"],
    ],
  },
];

function slopeInterpretation(slope: SlopeMetric): string {
  const value = Number(slope.value_bps);
  if (!Number.isFinite(value))
    return "Signal unavailable until all required tenors are live.";
  if (slope.label.includes("butterfly")) {
    if (value <= -15)
      return "Belly is rich versus wings; curve is locally concave around 5Y.";
    if (value >= 15)
      return "Belly is cheap versus wings; curve is locally convex around 5Y.";
    return "Belly is close to fair versus 2Y and 10Y wings.";
  }
  if (slope.label === "3m10y") {
    if (value < 0)
      return "Front-end inversion warns policy is restrictive versus long growth pricing.";
    if (value < 50) return "Curve is only lightly positive from bills to 10Y.";
    return "Long end is clearly above bills; the bills-to-10Y spread is wide.";
  }
  if (value < 0)
    return "Inverted spread; front end is leading and duration risk is defensive.";
  if (value < 35)
    return "Flat positive spread; curve has limited carry cushion.";
  if (value < 90)
    return "Normal positive slope; long-end yield pickup is meaningful.";
  return "Steep spread; the long end is well above the front end.";
}

// A slope is the difference between two traded yields and nothing else.  Naming it a
// term premium promotes a shape into an estimate of compensation for duration risk,
// which only a model can produce -- here, the Cleveland Fed's, whose figure appears in
// the decomposition section with its own vintage and its own uncertainty.

export function CurveDesk({
  snapshot,
  errorMessage,
  subStates,
}: {
  snapshot: Snapshot | null;
  errorMessage?: string;
  /**
   * `sub_states` from `/api/macro/rates`, CITED beside the snapshot.
   *
   * A second publisher on a tab whose comment used to say "one publisher", and settled
   * separately for the same reason tab 03 cites the rates domain: an outage in the state
   * engine must cost three verdicts, not the whole curve. Empty when that request failed
   * or the engine has not run — the sub-state panels then show their readings alone.
   */
  subStates?: components["schemas"]["MacroSubStateItem"][] | null;
}) {
  if (!snapshot) {
    return (
      <DeskEmptyState
        eyebrow="US Rates Factor Desk"
        errorMessage={errorMessage}
      />
    );
  }

  const summary = snapshot.summary ?? [];
  const curve = snapshot.curve ?? { points: [], slopes: [] };
  const policy: Policy = snapshot.policy ?? {
    status: "partial",
    plumbing: [],
    implied_path: [],
  };
  const positioning: Positioning = (snapshot.positioning ?? {
    rows: [],
    details: [],
    status: "missing",
  }) as Positioning;
  const cross = snapshot.cross_market;
  const supply = snapshot.supply as Supply | undefined;
  // UNKNOWN, not NEUTRAL: an absent scorecard is the absence of a view, and
  // "NEUTRAL" is a view.
  const scorecard = snapshot.scorecard ?? {
    duration_stance: "UNKNOWN",
    curve_stance: "NEUTRAL",
    groups: [],
  };
  const decomposition: Decomposition = snapshot.decomposition ?? {
    status: "missing",
    attribution: [],
  };
  const subStateFor = (role: string) =>
    (subStates ?? []).find((s) => s.role === role);

  return (
    <div className={styles.page}>
      <div className="board">
        {/* Board t2. No state pill here, and that is the board's call rather than an
          omission: this tab is the market's side, and the policy/rates state it would
          show belongs to — and is already shown on — tab 01. */}
        <DeskHeader
          title="Rates · Curve"
          questions={["Q2", "Q4", "Q5"]}
          standfirst={
            <>
              Split out of the Fed tab deliberately:{" "}
              <b>
                what the committee intends and what the term structure is
                pricing are two different questions
              </b>
              . This tab is the market&apos;s side. The curve prints the level,
              the decompositions say what is inside it, the attribution says who
              moved it, and the auction table says whether anyone absorbed it.
            </>
          }
          snapshot={snapshot}
          nav={NAV}
          navLabel="Rates curve sections"
        />

        <RatesTier
          id="tier-market"
          title="What the market prices"
          lede="The traded curve, its slopes, and what moved them."
        />

        <RatesSection id="summary" title="Summary" eyebrow="Live FRED curve">
          <div className={styles.summaryStack}>
            <div className={styles.kpiGrid}>
              {summary.map((tile) => (
                <Tile key={tile.label} tile={tile} />
              ))}
            </div>
          </div>
        </RatesSection>

        <RatesSection
          id="curve"
          title="Yield Curve"
          eyebrow="Nominal Treasury curve"
        >
          <RatesCurveChart points={curve.points ?? []} />
          <div className={styles.slopeCards}>
            {(curve.slopes ?? []).map((slope) => (
              <article
                key={slope.label}
                className={styles.slopeCard}
                data-testid="slope-card"
              >
                <span>{slope.label}</span>
                <strong>{fmtValue(slope.value_bps, "bps", 1)}</strong>
                <p>{slopeInterpretation(slope)}</p>
              </article>
            ))}
          </div>
        </RatesSection>

        {/* The board's three decomposition panels. They were one section until
          2026-08-29, which let a monthly model's output inherit the authority of
          arithmetic on traded yields. */}
        <NominalDecompositionSection
          decomposition={decomposition}
          policy={policy}
          slopes={curve.slopes ?? []}
        />
        <ClevelandDecompositionSection decomposition={decomposition} />
        <MoveAttributionSection decomposition={decomposition} />

        <RatesTier
          id="tier-mechanics"
          title="Mechanics"
          lede="The plumbing a rates view stands on: issuance, positioning and cross-market."
        />

        {/* The board's three SUB-STATE panels, in its order. Each pairs the engine's
          verdict (from `/api/macro/rates`) with the readings it was computed from (from
          the snapshot) -- see `SubStateSection` for why both belong on screen.

          A sub-state the engine did not publish renders its snapshot readings alone
          rather than vanishing: the readings are facts about the tape and do not stop
          being true because the verdict is missing. */}
        {subStateFor("supply") ? (
          <SubStateSection subState={subStateFor("supply")!}>
            <SupplyFiscalSection supply={supply} />
          </SubStateSection>
        ) : (
          <RatesSection
            id="substate-supply"
            title="Supply SUB-STATE"
            status={statusLabel(supply?.status)}
          >
            <SupplyFiscalSection supply={supply} />
          </RatesSection>
        )}

        {subStateFor("positioning") ? (
          <SubStateSection subState={subStateFor("positioning")!}>
            <PositioningSection positioning={positioning} />
          </SubStateSection>
        ) : (
          <RatesSection
            id="substate-positioning"
            title="Positioning SUB-STATE · 10Y futures"
            status={statusLabel(positioning?.status)}
          >
            <PositioningSection positioning={positioning} />
          </RatesSection>
        )}

        {/* Funding is the board's name for what the engine calls `plumbing`. Tab 01
          carries a `Plumbing` panel too and they are NOT duplicates: that one is the
          balance sheet behind the policy rate, this one is whether funding markets are
          transmitting it. */}
        {subStateFor("plumbing") ? (
          <SubStateSection subState={subStateFor("plumbing")!}>
            <div className={styles.compactGrid}>
              {(policy.plumbing ?? []).map((tile) => (
                <Tile key={tile.label} tile={tile} />
              ))}
            </div>
          </SubStateSection>
        ) : (
          // Rendered unconditionally, like its two siblings. `NAV` links to this anchor
          // on every render, so a section that appeared only when the state engine had
          // published would make the nav link to nowhere exactly when the engine is down.
          <RatesSection
            id="substate-plumbing"
            title="Funding SUB-STATE"
            status={statusLabel(policy?.status)}
          >
            <div className={styles.compactGrid}>
              {(policy.plumbing ?? []).map((tile) => (
                <Tile key={tile.label} tile={tile} />
              ))}
            </div>
          </RatesSection>
        )}

        <RatesSection
          id="auctions"
          title="Auction demand · did anyone show up"
          eyebrow="TreasuryDirect · recent results"
          status={statusLabel(supply?.status)}
        >
          <AuctionDemandSection supply={supply} />
        </RatesSection>

        <RatesSection
          id="cross"
          title="Cross-Market"
          status={statusLabel(cross?.status)}
        >
          <div className={styles.compactGrid}>
            {(cross?.rows ?? []).map((tile) => (
              <Tile key={tile.label} tile={tile} />
            ))}
          </div>
        </RatesSection>

        <RatesTier
          id="tier-provenance"
          title="Provenance and legacy"
          lede="Where the numbers came from, and the older rule score kept for comparison only."
        />

        {/* The quarantine. The rule score is not deleted -- it is the only thing an
          operator can hold the policy/rates state up against -- but it is stated as a
          refusal before it is shown, so nobody reads a number this desk does not answer
          with as the answer. */}
        <RatesSection
          id="refuses"
          title="What this tab refuses"
          status="Experimental legacy"
        >
          <div className={`${styles.notePanel} ${styles.noteRefuse}`}>
            <p>
              This tab reports the traded curve and what moved it. It does not
              compose those readings into a single score, and it takes no stance
              from one — no directional duration call, no curve call, and no
              prose narrating either.
            </p>
            <p>
              The rule score below predates the policy / rates state engine and
              is kept for exactly one purpose: so an operator can hold the state
              on the Fed tab up against what the old weights said. It is a
              legacy artifact under dual-read, not a decision surface — nothing
              else on this desk reads it, and no view here is derived from it.
            </p>
          </div>
          <RatesScorecard scorecard={scorecard} />
        </RatesSection>

        <SourceFreshnessSection snapshot={snapshot} />
      </div>
    </div>
  );
}
