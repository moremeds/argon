import { DealerPathChart } from "./DealerPathChart";
import { PolicyPathComparison } from "./PolicyPathComparison";
import { RatesCurveChart } from "./RatesCurveChart";
import styles from "./RatesDesk.module.css";
import { RatesScorecard } from "./RatesScorecard";
import { RatesSection, RatesTier } from "./RatesSection";
import { SepDotPlot } from "./SepDotPlot";
import { fmtSigned, fmtValue, statusLabel, toFiniteNumber } from "./format";
import { DecompositionSection } from "./sections/DecompositionSection";
import { PolicySection } from "./sections/PolicySection";
import { PositioningSection } from "./sections/PositioningSection";
import { StateSection } from "./sections/StateSection";
import { SupplySection } from "./sections/SupplySection";
import type {
  Decomposition,
  Policy,
  PolicyComparison,
  Positioning,
  Scorecard,
  SlopeMetric,
  Snapshot,
  SummaryTile,
  Supply,
} from "./types";

/**
 * The desk in reading order: the answer, who said it, what the market pays, the
 * plumbing underneath, and finally where it all came from.
 *
 * Grouped rather than flat because the old fifteen-item strip ordered panels by
 * nothing at all -- "Scorecard" (experimental legacy) sat between "Decomp" and
 * "Policy" with the same weight as the state itself.
 */
const NAV = [
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
    lede: "The plumbing a rates view stands on: policy settings, issuance, positioning, cross-market.",
    items: [
      ["policy", "Policy"],
      ["supply", "Supply"],
      ["positioning", "Positioning"],
      ["cross", "Cross-market"],
    ],
  },
  {
    id: "tier-provenance",
    tier: "Provenance and legacy",
    lede: "Where the numbers came from, and the older rule score kept for comparison only.",
    items: [
      ["events", "Events"],
      ["sources", "Sources"],
      ["scorecard", "Scorecard"],
      ["synthesis", "View"],
    ],
  },
] as const;

const FED_BOARD_SERIES = new Set([
  "DGS1MO",
  "DGS3MO",
  "DGS6MO",
  "DGS1",
  "DGS2",
  "DGS3",
  "DGS5",
  "DGS7",
  "DGS10",
  "DGS20",
  "DGS30",
  "DFII5",
  "DFII7",
  "DFII10",
  "DFII20",
  "DFII30",
  "WALCL",
  "WRESBAL",
  "WTREGEN",
]);

const ST_LOUIS_FED_SERIES = new Set(["T5YIE", "T10YIE", "T5YIFR"]);

function isClevelandFedSeries(seriesId: string): boolean {
  return seriesId.startsWith("CLEVE_");
}

function formatComputedAt(value: string): string {
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "computed time unavailable";
  return new Intl.DateTimeFormat("en-CA", {
    timeZone: "Asia/Hong_Kong",
    year: "numeric",
    month: "2-digit",
    day: "2-digit",
    hour: "2-digit",
    minute: "2-digit",
    hour12: false,
  })
    .format(date)
    .replace(",", "");
}

function sourcePublisher(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) {
    return "Cleveland Fed Inflation Expectations";
  }
  if (FED_BOARD_SERIES.has(seriesId)) return "FRED / Board of Governors";
  if (ST_LOUIS_FED_SERIES.has(seriesId)) return "FRED / St. Louis Fed";
  if (seriesId === "EFFR" || seriesId === "SOFR" || seriesId === "RRPONTSYD") {
    return "FRED / New York Fed";
  }
  return "FRED";
}

function fredSeriesUrl(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) {
    return "https://www.clevelandfed.org/indicators-and-data/inflation-expectations";
  }
  return `https://fred.stlouisfed.org/series/${encodeURIComponent(seriesId)}`;
}

function sourceLinkLabel(seriesId: string): string {
  if (isClevelandFedSeries(seriesId)) return `Cleveland Fed ${seriesId}`;
  return `FRED ${seriesId}`;
}

function snapshotMeta(snapshot: Snapshot): string {
  return `Snapshot update · ${formatComputedAt(
    snapshot.computed_at,
  )} HKT · FRED as of ${snapshot.as_of}`;
}

function deltaClass(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n) || n === 0) return styles.deltaNeutral;
  return n > 0 ? styles.deltaPositive : styles.deltaNegative;
}

function deltaUnit(tile: SummaryTile): string {
  if (tile.unit === "%" || tile.unit === "bps") return "bps 1D";
  return tile.unit ? `${tile.unit} 1D` : "1D";
}

function Tile({ tile }: { tile: SummaryTile }) {
  return (
    <article className={styles.kpiTile}>
      <span>{tile.label}</span>
      <strong>
        {fmtValue(tile.value, tile.unit, tile.unit === "bps" ? 1 : 2)}
      </strong>
      <small className={deltaClass(tile.delta_1d)}>
        {fmtSigned(tile.delta_1d, deltaUnit(tile))}
      </small>
    </article>
  );
}

function stanceToneClass(kind: "duration" | "curve", stance: string): string {
  if (kind === "duration") {
    if (stance === "BUY") return styles.stancePositive;
    if (stance === "SELL") return styles.stanceNegative;
    return styles.stanceNeutral;
  }
  if (stance === "STEEP") return styles.stanceNegative;
  if (stance === "FLAT") return styles.stancePositive;
  return styles.stanceNeutral;
}

function stanceDescription(
  kind: "duration" | "curve",
  stance: string,
  fallback: string | undefined,
): string {
  // UNKNOWN is checked before the fallback: the synthesis sentence is generated from
  // the same composite and must not narrate a lean the stance has already refused.
  if (kind === "duration" && stance === "UNKNOWN")
    return fallback ?? "Not enough scored inputs to take a duration view.";
  if (fallback) return fallback;
  if (kind === "duration") {
    if (stance === "BUY") return "Rule score favors owning duration.";
    if (stance === "SELL") return "Rule score favors underweighting duration.";
    return "Rule score is balanced; duration signal is neutral.";
  }
  if (stance === "STEEP") return "Rule score favors a steeper curve.";
  if (stance === "FLAT") return "Rule score favors a flatter curve.";
  return "Rule score is balanced; curve signal is neutral.";
}

function StanceCard({
  label,
  kind,
  stance,
  description,
}: {
  label: string;
  kind: "duration" | "curve";
  stance: string;
  description: string;
}) {
  return (
    <article
      className={[styles.stanceCard, stanceToneClass(kind, stance)].join(" ")}
      data-watermark={stance}
    >
      <span className={styles.stanceLabel}>{label}</span>
      <strong>{stance}</strong>
      <p>{description}</p>
      <span className={styles.stanceWatermark} aria-hidden="true">
        {stance}
      </span>
    </article>
  );
}

function SummaryStances({
  scorecard,
  synthesis,
}: {
  scorecard: Scorecard;
  synthesis: Snapshot["synthesis"];
}) {
  return (
    <div className={styles.stanceGrid} data-testid="legacy-stance-grid">
      <StanceCard
        label="Duration stance"
        kind="duration"
        stance={scorecard.duration_stance}
        description={stanceDescription(
          "duration",
          scorecard.duration_stance,
          synthesis?.duration_view ?? scorecard.coverage_detail ?? undefined,
        )}
      />
      <StanceCard
        label="Curve stance"
        kind="curve"
        stance={scorecard.curve_stance}
        description={stanceDescription(
          "curve",
          scorecard.curve_stance,
          synthesis?.curve_view,
        )}
      />
    </div>
  );
}

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

export function RatesDesk({
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
    const hasError = Boolean(errorMessage);
    return (
      <div className={styles.page}>
        <div className={styles.emptyState}>
          <p className={styles.eyebrow}>US Rates Factor Desk</p>
          <h1>
            {hasError ? "Rates API unavailable" : "Rates snapshot not computed"}
          </h1>
          <p>
            {hasError
              ? errorMessage
              : "Run the live FRED backfill or wait for the scheduled worker refresh."}
          </p>
        </div>
      </div>
    );
  }

  const summary = snapshot.summary ?? [];
  const curve = snapshot.curve ?? { points: [], slopes: [] };
  const policy: Policy = snapshot.policy ?? {
    status: "partial",
    plumbing: [],
    implied_path: [],
  };
  const supply = snapshot.supply as Supply | undefined;
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
      <header className={styles.header}>
        <div className={styles.headerTop}>
          <div className={styles.titleLockup}>
            <h1>
              US Rates Factor Desk<span>.</span>
            </h1>
            <p>Treasury Factor Board</p>
          </div>
          <p className={styles.headerMeta}>{snapshotMeta(snapshot)}</p>
        </div>
        <nav className={styles.nav} aria-label="Rates sections">
          {NAV.map((group) => (
            <span key={group.id} className={styles.navGroup}>
              <a href={`#${group.id}`} className={styles.navGroupLabel}>
                {group.tier}
              </a>
              {group.items.map(([id, label]) => (
                <a key={id} href={`#${id}`}>
                  {label}
                </a>
              ))}
            </span>
          ))}
        </nav>
      </header>

      <RatesTier id="tier-answer" title="The answer" lede="What this desk says about policy right now, and how sure it is." />

      <RatesSection
        id="state"
        title="Policy / Rates State"
        eyebrow="Point-in-time evidence"
      >
        <StateSection state={snapshot.state} />
      </RatesSection>

      <RatesTier id="tier-publishers" title="Who says what" lede="Each publisher on its own axes, and how far it has moved since its last release." />

      <RatesSection
        id="paths"
        title="Policy Paths"
      >
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

      <RatesTier id="tier-market" title="What the market prices" lede="The traded curve, its slopes, and what moved them." />

      <RatesSection id="summary" title="Summary" eyebrow="Live FRED curve">
        <div className={styles.summaryStack}>
          <div className={styles.kpiGrid}>
            {summary.map((tile) => (
              <Tile key={tile.label} tile={tile} />
            ))}
          </div>
          <p className={styles.legacyBanner}>
            Experimental legacy · the stances below come from the rule score, not
            from the state above.
          </p>
          <SummaryStances
            scorecard={scorecard}
            synthesis={snapshot.synthesis}
          />
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

      <RatesTier id="tier-mechanics" title="Mechanics" lede="The plumbing a rates view stands on: policy settings, issuance, positioning, cross-market." />

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

      <RatesTier id="tier-provenance" title="Provenance and legacy" lede="Where the numbers came from, and the older rule score kept for comparison only." />

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

      <RatesSection
        id="sources"
        title="Source Freshness"
        eyebrow="FRED observations"
      >
        <div className={styles.sourceGrid}>
          {(snapshot.source_freshness ?? []).map((source) => (
            <div key={source.id} className={styles.sourceRow}>
              <strong>{source.label || source.id}</strong>
              <span>{sourcePublisher(source.id)}</span>
              <span>Latest obs {source.latest_obs_date ?? "n/a"}</span>
              <span>{statusLabel(source.status)}</span>
              <a
                href={fredSeriesUrl(source.id)}
                target="_blank"
                rel="noreferrer"
              >
                {sourceLinkLabel(source.id)}
              </a>
            </div>
          ))}
        </div>
      </RatesSection>

      <RatesSection
        id="scorecard"
        title="Scorecard"
        eyebrow="Rule weights"
        status="Experimental legacy"
      >
        <RatesScorecard scorecard={scorecard} />
      </RatesSection>

      <RatesSection id="synthesis" title="Synthesis">
        <div className={styles.synthesis}>
          <p>{snapshot.synthesis.duration_view}</p>
          <p>{snapshot.synthesis.curve_view}</p>
          {(snapshot.synthesis.risks ?? []).map((risk) => (
            <span key={risk}>{risk}</span>
          ))}
        </div>
      </RatesSection>

      {/* Two publishers, two blocks, two sets of axes. Plotted rather than listed
          because the point of each release is its dispersion, and a column of medians
          is the one view that hides it. Kept apart because a shared frame would read
          as a comparison the desk refuses to make. */}























    </div>
  );
}
