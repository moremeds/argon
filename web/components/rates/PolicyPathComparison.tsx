import styles from "./RatesDesk.module.css";
import { fmtValue, toFiniteNumber } from "./format";
import { isWithheld, releaseDate } from "./policyPath";
import type {
  MacroPolicyPathPoint,
  PolicyComparison,
  PolicyPath,
  PolicyPathSlot,
} from "./types";

// Four publishers answer the same question and disagree, and the disagreement is the
// information. So each path gets its own lane with its own source and release date,
// and nothing on this surface averages them: a blended "Fed path" would be a number
// no committee voted on, no dealer forecast, and no market traded.

const LANES: {
  kind: PolicyPathSlot["kind"];
  title: string;
  question: string;
  /** Anchor of the chart below that draws this lane's full path, if there is one. */
  plotId?: string;
}[] = [
  {
    kind: "actual",
    title: "Actual",
    question: "What the FOMC decided.",
  },
  {
    kind: "committee_projection",
    plotId: "sep-plot",
    title: "Committee projection (SEP)",
    question: "Where participants projected rates, anonymously.",
  },
  {
    kind: "dealer_expectations",
    plotId: "dealer-plot",
    title: "Dealer expectations",
    question: "What surveyed dealers said they expect.",
  },
  {
    kind: "market_implied",
    title: "Market-implied",
    question: "What a third party reads out of traded prices.",
  },
];

function sourceKindLabel(kind: string): string {
  if (kind === "official") return "Official";
  if (kind === "first_party_publisher") return "First-party publisher";
  if (kind === "entitled_provider") return "Entitled provider";
  if (kind === "third_party_shadow") return "Third-party shadow · not official";
  return "Non-production source";
}

function delayLabel(path: PolicyPath): string | null {
  if (path.kind !== "market_implied") return null;
  if (path.delay_status === "known") {
    return `${path.delay_minutes ?? 0} min delayed`;
  }
  if (path.delay_status === "unknown") return "delay unknown";
  return null;
}

function fmtRate(value: unknown): string {
  return fmtValue(value, "%", 2);
}

function targetRange(point: MacroPolicyPathPoint): string {
  const lower = point.target_range_lower_percent;
  const upper = point.target_range_upper_percent;
  if (lower == null || upper == null) return fmtRate(point.rate_percent);
  return `${toFiniteNumber(lower).toFixed(2)}–${toFiniteNumber(upper).toFixed(2)}%`;
}

/**
 * An empty `voted_against` means "no dissenter was NAMED". It equals "no dissent" only
 * when the publisher printed the roster, so the flag travels with the sentence.
 */
function voteLine(point: MacroPolicyPathPoint): string | null {
  if (point.vote_status === "not_stated") {
    return "Publisher printed no vote.";
  }
  const tally = point.vote_split ? `Vote ${point.vote_split}` : "Vote";
  const against = point.voted_against ?? [];
  if (point.voter_names_stated === true) {
    return against.length
      ? `${tally} · against: ${against.join(", ")}`
      : `${tally} · no dissent`;
  }
  if (point.voter_names_stated === false) {
    return against.length
      ? `${tally} · named against: ${against.join(", ")} · roster not printed`
      : `${tally} · no dissenter named; the publisher printed no roster`;
  }
  return point.vote_split ? tally : null;
}

function ActualPoints({ points }: { points: MacroPolicyPathPoint[] }) {
  return (
    <ul className={styles.pathPoints}>
      {points.map((point) => {
        const vote = voteLine(point);
        return (
          <li key={`${point.horizon}:${point.horizon_date ?? ""}`}>
            <span>{point.horizon_date ?? point.horizon}</span>
            <strong>{targetRange(point)}</strong>
            <small>
              {point.action ?? "action not stated"}
              {vote ? ` · ${vote}` : ""}
            </small>
          </li>
        );
      })}
    </ul>
  );
}

function SepPoints({ points }: { points: MacroPolicyPathPoint[] }) {
  return (
    <>
      <ul className={styles.pathPoints}>
        {points.map((point) => (
          <li key={`${point.horizon}:${point.horizon_date ?? ""}`}>
            <span>{point.horizon}</span>
            <strong>{fmtRate(point.rate_percent)}</strong>
            <small>
              {point.central_tendency_lower_percent != null &&
              point.central_tendency_upper_percent != null
                ? `central tendency ${toFiniteNumber(point.central_tendency_lower_percent).toFixed(2)}–${toFiniteNumber(point.central_tendency_upper_percent).toFixed(2)}%`
                : "central tendency not published"}
              {point.participant_distribution?.length
                ? ` · ${point.participant_distribution.reduce((sum, dot) => sum + dot.participant_count, 0)} dots`
                : ""}
            </small>
          </li>
        ))}
      </ul>
      {/* The dot plot is published without names. Attaching one -- the Chair's above all
          -- would invent a fact the FOMC deliberately does not publish. */}
      <p className={styles.pathNote} data-testid="sep-anonymity-note">
        SEP dots are anonymous. No dot on this page is attributed to a named
        participant.
      </p>
    </>
  );
}

function DealerPoints({ points }: { points: MacroPolicyPathPoint[] }) {
  return (
    <ul className={styles.pathPoints}>
      {points.map((point) => (
        <li key={`${point.horizon}:${point.horizon_date ?? ""}`}>
          <span>{point.horizon}</span>
          <strong>{fmtRate(point.rate_percent)}</strong>
          <small>
            {point.p25_percent != null && point.p75_percent != null
              ? `IQR ${toFiniteNumber(point.p25_percent).toFixed(2)}–${toFiniteNumber(point.p75_percent).toFixed(2)}%`
              : "quartiles not published"}
            {point.respondent_count != null
              ? ` · n=${point.respondent_count}`
              : ""}
          </small>
        </li>
      ))}
    </ul>
  );
}

function MarketPoints({ points }: { points: MacroPolicyPathPoint[] }) {
  return (
    <ul className={styles.pathPoints}>
      {points.map((point) => {
        const buckets = point.probability_distribution ?? [];
        return (
          <li key={`${point.horizon}:${point.horizon_date ?? ""}`}>
            <span>{point.horizon_date ?? point.horizon}</span>
            <strong>{fmtRate(point.rate_percent)}</strong>
            <small>
              {buckets.length
                ? buckets
                    .map(
                      (bucket) =>
                        `${bucket.label} ${toFiniteNumber(bucket.probability_percent).toFixed(1)}%`,
                    )
                    .join(" · ")
                : "no probability distribution published"}
            </small>
          </li>
        );
      })}
    </ul>
  );
}

/**
 * The headline of a path whose every horizon is plotted directly below.
 *
 * The SEP and dealer lanes used to list all of their horizons -- sixteen rows for the
 * dealer survey -- immediately above the chart that draws exactly those numbers on an
 * axis. Two renderings of one release, the taller of which is the one that hides the
 * shape. The lane keeps what a lane is for (which publisher, which release, is it
 * healthy) plus the near-term number, and points at the plot for the rest.
 */
function PlottedSummary({ path, plotId }: { path: PolicyPath; plotId: string }) {
  const points = path.points ?? [];
  const first = points[0];
  const rate = first ? toFiniteNumber(first.rate_percent, Number.NaN) : Number.NaN;
  return (
    <div className={styles.pathSummary} data-testid="policy-path-summary">
      {first ? (
        <>
          <span className={styles.pathSummaryHorizon}>{first.horizon}</span>
          <strong className={styles.pathSummaryValue}>
            {Number.isFinite(rate) ? `${rate.toFixed(2)} %` : "n/a"}
          </strong>
        </>
      ) : null}
      <a className={styles.pathSummaryLink} href={`#${plotId}`}>
        {points.length} horizon{points.length === 1 ? "" : "s"} plotted below →
      </a>
      {/* Kept even in the collapsed lane. The per-horizon list this replaced carried
          the anonymity statement, and dropping it with the rest of the detail would
          have quietly removed a safety rule along with some duplication: the FOMC
          publishes these dots without names, and the desk says so wherever it shows
          them. */}
      {path.kind === "committee_projection" ? (
        <p className={styles.pathNote} data-testid="sep-anonymity-note">
          SEP dots are anonymous. No dot on this page is attributed to a named
          participant.
        </p>
      ) : null}
    </div>
  );
}

function PathPoints({ path }: { path: PolicyPath }) {
  const points = path.points ?? [];
  if (!points.length) {
    return (
      <p className={styles.pathNote}>
        The release carried no readable path point.
      </p>
    );
  }
  if (path.kind === "actual") return <ActualPoints points={points} />;
  if (path.kind === "committee_projection")
    return <SepPoints points={points} />;
  if (path.kind === "dealer_expectations")
    return <DealerPoints points={points} />;
  return <MarketPoints points={points} />;
}

function latestActualRelease(slot: PolicyPathSlot | undefined): string | null {
  const path = slot?.path;
  return path && !isWithheld(path) ? releaseDate(path) : null;
}

/**
 * Why a lane's newest release is older than the newest FOMC decision.
 *
 * A reader who knows the committee last met on 2026-07-29 and sees "released
 * 2026-06-17" on the SEP lane concludes the feed is stale. It is not: the FOMC
 * publishes projections at four of its eight annual meetings, and the dealer survey
 * runs per survey round rather than per meeting. That is derivable from what is
 * already on the page -- an `actual` release newer than this lane's -- so the page
 * states it rather than leaving the reader to diagnose a non-problem.
 *
 * Deliberately NOT a hardcoded meeting calendar: it says only what the two release
 * dates show, and goes quiet the moment the lane catches up.
 */
function behindActual(path: PolicyPath, latestActual: string | null): string | null {
  if (!latestActual) return null;
  const mine = releaseDate(path);
  return mine < latestActual
    ? `No release since ${mine}; the FOMC last decided on ${latestActual}.`
    : null;
}

function Lane({
  title,
  question,
  slot,
  plotId,
  latestActual,
}: {
  title: string;
  question: string;
  slot: PolicyPathSlot | undefined;
  /** Anchor of the chart that draws this lane's full path, when one exists. */
  plotId?: string;
  /** Release date of the newest FOMC decision, for the behind-actual note. */
  latestActual?: string | null;
}) {
  const path = slot?.path ?? null;
  const rejected =
    path != null && isWithheld(path);

  return (
    <article
      className={styles.pathLane}
      data-testid={`policy-path-lane-${slot?.kind ?? "unknown"}`}
      data-path-status={
        rejected ? "rejected" : path ? "available" : "unavailable"
      }
    >
      <div className={styles.pathLaneTop}>
        <h3>{title}</h3>
        {path ? (
          <span className={styles.pathSourceKind}>
            {sourceKindLabel(path.source_kind)}
          </span>
        ) : (
          <span className={styles.pathSourceKind}>No path</span>
        )}
      </div>
      <p className={styles.pathQuestion}>{question}</p>

      {path ? (
        <>
          <p className={styles.pathProvenance}>
            {path.source} · released {releaseDate(path)}
            {delayLabel(path) ? ` · ${delayLabel(path)}` : ""}
          </p>
          {rejected ? (
            // Representable in the contract, so refused here rather than assumed away.
            <p className={styles.pathRejected}>
              Rejected: this lane is carrying {path.source_kind} evidence, which
              is not a publisher. Its numbers are withheld rather than shown as
              a path.
            </p>
          ) : plotId ? (
            <PlottedSummary path={path} plotId={plotId} />
          ) : (
            <PathPoints path={path} />
          )}
        </>
      ) : (
        <p className={styles.pathMissing}>
          {slot?.missing_reason ?? "This path has not been ingested."}
        </p>
      )}

      {path && !rejected && behindActual(path, latestActual ?? null) ? (
        <p className={styles.pathBehind} data-testid="policy-path-behind">
          {behindActual(path, latestActual ?? null)}
        </p>
      ) : null}

      {slot ? (
        <p className={styles.pathFreshness}>
          {slot.freshness.status}
          {/* The per-release catalog deliberately models only FOMC statements and
              SEPs -- the dealer survey and the market shadow are not FOMC releases
              and carry release_type=None. So their counters are structurally 0/0,
              and printing the ratio anyway put "0/0 releases parsed" underneath a
              lane showing twelve parsed surveys. A number that does not apply is
              not a neutral one; it reads as a broken feed. */}
          {slot.freshness.releases_discovered > 0
            ? ` · ${slot.freshness.releases_succeeded}/${slot.freshness.releases_discovered} releases parsed`
            : ""}
          {slot.freshness.releases_failed
            ? ` · ${slot.freshness.releases_failed} failed`
            : ""}
        </p>
      ) : null}
    </article>
  );
}

export function PolicyPathComparison({
  comparison,
  errorMessage,
}: {
  comparison: PolicyComparison | null | undefined;
  errorMessage?: string;
}) {
  if (!comparison) {
    return (
      <div className={styles.stateMissing} data-testid="policy-paths-missing">
        <strong>Policy paths unavailable</strong>
        <p>
          {errorMessage ??
            "No policy comparison has been assembled for this instant."}
        </p>
      </div>
    );
  }

  const slots: Record<string, PolicyPathSlot | undefined> = {
    actual: comparison.actual,
    committee_projection: comparison.committee_projection,
    dealer_expectations: comparison.dealer_expectations,
    market_implied: comparison.market_implied,
  };
  const contradictions = comparison.contradictions ?? [];

  return (
    <div className={styles.pathComparison} data-testid="policy-path-comparison">
      <p className={styles.pathIntro}>
        Four publishers, four lanes, never averaged — a blended path is a number
        nobody published.
      </p>
      <div className={styles.pathLanes}>
        {LANES.map((lane) => (
          <Lane
            key={lane.kind}
            title={lane.title}
            question={lane.question}
            slot={slots[lane.kind]}
            plotId={lane.plotId}
            latestActual={
              lane.kind === "actual" ? null : latestActualRelease(slots.actual)
            }
          />
        ))}
      </div>
      {contradictions.length ? (
        <ul
          className={styles.stateContradictions}
          data-testid="policy-path-contradictions"
        >
          {contradictions.map((item) => (
            <li key={item}>
              <span>{item}</span>
            </li>
          ))}
        </ul>
      ) : null}
    </div>
  );
}
