import { RatesCurveChart } from "./RatesCurveChart";
import styles from "./RatesDesk.module.css";
import { RatesScorecard } from "./RatesScorecard";
import { RatesSection } from "./RatesSection";
import { fmtSigned, fmtValue, statusLabel, toFiniteNumber } from "./format";
import { DecompositionSection } from "./sections/DecompositionSection";
import { PolicySection } from "./sections/PolicySection";
import { PositioningSection } from "./sections/PositioningSection";
import { SupplySection } from "./sections/SupplySection";
import type {
  Decomposition,
  Policy,
  Positioning,
  Scorecard,
  SlopeMetric,
  Snapshot,
  SummaryTile,
  Supply,
} from "./types";

const NAV = [
  ["summary", "Summary"],
  ["curve", "Curve"],
  ["decomp", "Decomp"],
  ["scorecard", "Scorecard"],
  ["policy", "Policy"],
  ["supply", "Supply"],
  ["positioning", "Positioning"],
  ["cross", "Cross-Market"],
  ["events", "Events"],
  ["synthesis", "View"],
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
    <div className={styles.stanceGrid}>
      <StanceCard
        label="Duration stance"
        kind="duration"
        stance={scorecard.duration_stance}
        description={stanceDescription(
          "duration",
          scorecard.duration_stance,
          synthesis?.duration_view,
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
    if (value < 50)
      return "Term premium is modest; curve is only lightly positive from bills to 10Y.";
    return "Long end is clearly above bills; easing or term premium pressure is visible.";
  }
  if (value < 0)
    return "Inverted spread; front end is leading and duration risk is defensive.";
  if (value < 35)
    return "Flat positive spread; curve has limited carry cushion.";
  if (value < 90)
    return "Normal positive slope; long-end yield pickup is meaningful.";
  return "Steep spread; long-end supply, inflation, or term premium is dominating.";
}

export function RatesDesk({
  snapshot,
  errorMessage,
}: {
  snapshot: Snapshot | null;
  errorMessage?: string;
}) {
  if (!snapshot) {
    const hasError = Boolean(errorMessage);
    return (
      <div className={styles.page}>
        <div className={styles.emptyState}>
          <p className={styles.eyebrow}>US Rates Factor Desk</p>
          <h1>{hasError ? "Rates API unavailable" : "Rates snapshot not computed"}</h1>
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
  const scorecard = snapshot.scorecard ?? {
    duration_stance: "NEUTRAL",
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
          <p className={styles.headerMeta}>
            {snapshotMeta(snapshot)}
          </p>
        </div>
        <nav className={styles.nav} aria-label="Rates sections">
          {NAV.map(([id, label]) => (
            <a
              key={id}
              href={`#${id}`}
              className={id === "summary" ? styles.navActive : undefined}
            >
              {label}
            </a>
          ))}
        </nav>
      </header>

      <RatesSection id="summary" title="Summary" eyebrow="Live FRED curve">
        <div className={styles.summaryStack}>
          <div className={styles.kpiGrid}>
            {summary.map((tile) => (
              <Tile key={tile.label} tile={tile} />
            ))}
          </div>
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
            <article key={slope.label} className={styles.slopeCard}>
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

      <RatesSection id="scorecard" title="Scorecard" eyebrow="Rule weights">
        <RatesScorecard scorecard={scorecard} />
      </RatesSection>

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

      <RatesSection id="synthesis" title="Synthesis">
        <div className={styles.synthesis}>
          <p>{snapshot.synthesis.duration_view}</p>
          <p>{snapshot.synthesis.curve_view}</p>
          {(snapshot.synthesis.risks ?? []).map((risk) => (
            <span key={risk}>{risk}</span>
          ))}
        </div>
      </RatesSection>
    </div>
  );
}
