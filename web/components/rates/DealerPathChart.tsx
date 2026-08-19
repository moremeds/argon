import styles from "./RatesDesk.module.css";
import { toFiniteNumber } from "./format";
import { plottable, releaseDate } from "./policyPath";
import type { MacroPolicyPathPoint, PolicyPathSlot } from "./types";

/**
 * The New York Fed's dealer survey as a path with its own dispersion band.
 *
 * The list this replaces printed "3.63 %" seven times in a column, which is the
 * survey's actual answer and also unreadable: the eye cannot see that the median is
 * pinned flat through early 2027 and only then rolls over, nor that the quartile band
 * opens months before the median moves. On an axis both are the first thing you see.
 *
 * Its own axes, deliberately. Overlaying this on the SEP would draw a comparison the
 * desk refuses to make numerically -- two publishers answering the same question are
 * kept in separate frames so neither is read as confirming the other.
 */

const WIDTH = 780;
const HEIGHT = 400;
const PAD_LEFT = 56;
const PAD_RIGHT = 28;
const PAD_TOP = 26;
const PAD_BOTTOM = 56;
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT;
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM;

type Row = {
  index: number;
  horizon: string;
  median: number;
  p25: number | null;
  p75: number | null;
  respondents: number | null;
};

/** "Jun. 16-17 2026" -> "Jun 26"; "2027 Q2" -> "27Q2"; "2029" -> "2029". */
export function shortHorizon(horizon: string): string {
  const quarter = horizon.match(/^(\d{4})\s*Q([1-4])$/);
  if (quarter) return `${quarter[1].slice(2)}Q${quarter[2]}`;
  const meeting = horizon.match(/^([A-Za-z]{3})[a-z]*\.?\s.*?(\d{4})$/);
  if (meeting) return `${meeting[1]} ${meeting[2].slice(2)}`;
  return horizon;
}

function numberOrNull(value: unknown): number | null {
  if (value == null) return null;
  const n = toFiniteNumber(value, Number.NaN);
  return Number.isFinite(n) ? n : null;
}

function toRows(points: MacroPolicyPathPoint[]): Row[] {
  return points
    .map((point, index) => ({
      index,
      horizon: point.horizon,
      median: toFiniteNumber(point.rate_percent, Number.NaN),
      p25: numberOrNull(point.p25_percent),
      p75: numberOrNull(point.p75_percent),
      respondents: numberOrNull(point.respondent_count),
    }))
    .filter((row) => Number.isFinite(row.median));
}

function respondentNote(rows: Row[]): string {
  const counts = rows
    .map((row) => row.respondents)
    .filter((n): n is number => n != null);
  if (!counts.length) return "Respondent count not published.";
  const lo = Math.min(...counts);
  const hi = Math.max(...counts);
  // A shrinking panel at the long end is a fact about the survey, not a detail: the
  // far horizons are answered by fewer dealers than the near ones.
  return lo === hi
    ? `n=${lo} at every horizon.`
    : `n varies by horizon, ${lo}–${hi}; the far horizons are answered by fewer dealers.`;
}

export function DealerPathChart({
  slot,
}: {
  slot: PolicyPathSlot | null | undefined;
}) {
  const resolved = plottable(slot);
  if (resolved.status === "empty") {
    return (
      <div className={styles.stateMissing} data-testid="dealer-path-missing">
        <strong>No dealer survey to plot</strong>
        <p>{resolved.reason}</p>
      </div>
    );
  }

  const path = resolved.path;
  const rows = toRows(path.points ?? []);
  if (!rows.length) {
    return (
      <div className={styles.stateMissing} data-testid="dealer-path-missing">
        <strong>No dealer survey to plot</strong>
        <p>
          The release parsed, but carried no numeric expectation to place on an
          axis.
        </p>
      </div>
    );
  }

  const values = rows.flatMap((row) =>
    [row.median, row.p25, row.p75].filter((n): n is number => n != null),
  );
  const lo = Math.min(...values) - 0.15;
  const hi = Math.max(...values) + 0.15;
  const span = Math.max(hi - lo, 0.5);
  const step = PLOT_W / Math.max(rows.length - 1, 1);

  const xFor = (index: number) => PAD_LEFT + step * index;
  const yFor = (value: number) => PAD_TOP + (1 - (value - lo) / span) * PLOT_H;

  // The band is drawn only across the run where both quartiles exist, so a gap in the
  // publisher's dispersion shows as a gap rather than as a straight interpolation.
  const banded = rows.filter((row) => row.p25 != null && row.p75 != null);
  const bandPoints = banded.length
    ? [
        ...banded.map((row) => `${xFor(row.index)},${yFor(row.p75 as number)}`),
        ...banded
          .slice()
          .reverse()
          .map((row) => `${xFor(row.index)},${yFor(row.p25 as number)}`),
      ].join(" ")
    : "";

  const medianPoints = rows
    .map((row) => `${xFor(row.index)},${yFor(row.median)}`)
    .join(" ");
  const ticks = Array.from({ length: 5 }, (_, i) => lo + (span * i) / 4);

  return (
    <div className={styles.pathChartBlock}>
      <div className={styles.chartPanel} aria-label="Dealer expectations chart">
        <div className={styles.chartHeader}>
          <strong>Expected policy rate by horizon</strong>
          <div className={styles.chartLegend}>
            <span>
              <i className={styles.dealerMedianSwatch} />
              Median
            </span>
            <span>
              <i className={styles.dealerBandSwatch} />
              Interquartile range
            </span>
          </div>
        </div>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label="New York Fed Survey of Market Expectations: median expected policy rate with interquartile range by horizon"
        >
          <rect
            x="0"
            y="0"
            width={WIDTH}
            height={HEIGHT}
            rx="8"
            fill="var(--bg-panel)"
          />
          {ticks.map((tick) => (
            <g key={tick.toFixed(3)}>
              <line
                x1={PAD_LEFT}
                x2={WIDTH - PAD_RIGHT}
                y1={yFor(tick)}
                y2={yFor(tick)}
                stroke="var(--border-dim)"
              />
              <text
                x={PAD_LEFT - 10}
                y={yFor(tick) + 4}
                textAnchor="end"
                className={styles.svgLabel}
              >
                {tick.toFixed(2)}
              </text>
            </g>
          ))}

          {bandPoints ? (
            <polygon
              points={bandPoints}
              className={styles.dealerBand}
              data-testid="dealer-path-band"
            />
          ) : null}

          <polyline
            points={medianPoints}
            fill="none"
            className={styles.dealerMedian}
            strokeWidth="3"
            strokeLinejoin="round"
            strokeLinecap="round"
          />

          {rows.map((row) => (
            <g key={`${row.horizon}:${row.index}`}>
              <circle
                cx={xFor(row.index)}
                cy={yFor(row.median)}
                r="4"
                className={styles.dealerDot}
              >
                <title>
                  {`${row.horizon}: median ${row.median.toFixed(2)}%` +
                    (row.p25 != null && row.p75 != null
                      ? ` · IQR ${row.p25.toFixed(2)}–${row.p75.toFixed(2)}%`
                      : " · quartiles not published") +
                    (row.respondents != null ? ` · n=${row.respondents}` : "")}
                </title>
              </circle>
              {/* Sixteen horizons do not fit on one baseline, so labels alternate rows
                  rather than being dropped: a hidden horizon is a hidden data point. */}
              <text
                x={xFor(row.index)}
                y={HEIGHT - (row.index % 2 === 0 ? 28 : 13)}
                textAnchor="middle"
                className={styles.svgLabel}
              >
                {shortHorizon(row.horizon)}
              </text>
            </g>
          ))}
        </svg>
      </div>

      <p className={styles.pathProvenance}>
        {path.source} · released {releaseDate(path)}
      </p>
      <p className={styles.pathNote} data-testid="dealer-path-note">
        {`${respondentNote(rows)} `}
        Plotted on its own axes — this survey is never merged with, or averaged
        against, the committee&apos;s own projection.
      </p>
    </div>
  );
}
