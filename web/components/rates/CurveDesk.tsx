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
import { DecompositionSection } from "./sections/DecompositionSection";
import { PositioningSection } from "./sections/PositioningSection";
import type {
  Decomposition,
  Policy,
  Positioning,
  SlopeMetric,
  Snapshot,
} from "./types";

/**
 * Macro desk tab 02 — Rates · Curve.
 *
 * The market's half of the old `/rates` page: what the traded curve prices, what moved
 * it, and the positioning and cross-market plumbing that stands beside it. The Fed's own
 * state and the four published policy paths live on tab 01, `FedDesk`.
 *
 * `/rates` 308s here rather than to tab 01 (`next.config.mjs`), so this tab keeps the old
 * page's title lockup: an inbound link that said "US Rates Factor Desk" should land
 * somewhere that still says it.
 */
const NAV: readonly NavGroup[] = [
  {
    id: "tier-market",
    tier: "What the market prices",
    lede: "The traded curve, its slopes, and what moved them.",
    items: [
      ["summary", "Summary"],
      ["curve", "Curve"],
      ["decomp", "Decomposition"],
    ],
  },
  {
    id: "tier-mechanics",
    tier: "Mechanics",
    // The old lede named four panels ("policy settings, issuance, positioning,
    // cross-market"); the first two now live on tab 01, so the sentence names what this
    // tab actually carries rather than staying verbatim and going false.
    lede: "The plumbing a rates view stands on: positioning and cross-market.",
    items: [
      ["positioning", "Positioning"],
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
}: {
  snapshot: Snapshot | null;
  errorMessage?: string;
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

  return (
    <div className={styles.page}>
      <DeskHeader
        title="US Rates Factor Desk"
        subtitle="Treasury Factor Board"
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

      <DecompositionSection
        decomposition={decomposition}
        policy={policy}
        slopes={curve.slopes ?? []}
      />

      <RatesTier
        id="tier-mechanics"
        title="Mechanics"
        lede="The plumbing a rates view stands on: positioning and cross-market."
      />

      <RatesSection
        id="positioning"
        title="Positioning"
        status={statusLabel(positioning?.status)}
      >
        <PositioningSection positioning={positioning} />
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
        <div className={styles.notePanel}>
          <p>
            This tab reports the traded curve and what moved it. It does not
            compose those readings into a single score, and it takes no stance
            from one — no directional duration call, no curve call, and no prose
            narrating either.
          </p>
          <p>
            The rule score below predates the policy / rates state engine and is
            kept for exactly one purpose: so an operator can hold the state on
            the Fed tab up against what the old weights said. It is a legacy
            artifact under dual-read, not a decision surface — nothing else on
            this desk reads it, and no view here is derived from it.
          </p>
        </div>
        <RatesScorecard scorecard={scorecard} />
      </RatesSection>

      <SourceFreshnessSection snapshot={snapshot} />
    </div>
  );
}
