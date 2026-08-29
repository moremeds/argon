import { WIDE_FRAME, axisTicks } from "@/components/macro/chartGeometry";
import { BoardRead } from "@/components/macro/domain/BoardPanel";
import styles from "./RatesDesk.module.css";
import { finiteOrNull, toFiniteNumber } from "./format";
import { plottable, priorReleases, releaseDate } from "./policyPath";
import type { MacroPolicyPathPoint, PolicyPath, PolicyPathSlot } from "./types";

const {
  width: WIDTH,
  height: HEIGHT,
  padLeft: PAD_LEFT,
  padRight: PAD_RIGHT,
  padTop: PAD_TOP,
  plotW: PLOT_W,
  plotH: PLOT_H,
  xLabelNear: X_LABEL_NEAR,
} = WIDE_FRAME;

/**
 * The New York Fed's dealer survey as a path, with the surveys before it behind it.
 *
 * The list this replaces printed "3.63 %" seven times in a column, which is the
 * survey's actual answer and also unreadable: the eye cannot see that the median is
 * pinned flat through early 2027 and only then rolls over, nor that the quartile band
 * opens months before the median moves. On an axis both are the first thing you see.
 *
 * The x axis is TIME, not the survey's own row order, and that is what makes the
 * overlay honest. Each survey asks about the FOMC meetings ahead of it, so a March
 * release and a June release do not share a single horizon -- plotting them against
 * row index would draw March's first meeting on top of June's and call the difference
 * a revision. Against the meeting date they line up because they are the same dates.
 *
 * Still its own axes, deliberately. Overlaying this on the SEP would draw a comparison
 * the desk refuses to make numerically -- two PUBLISHERS answering the same question
 * are kept in separate frames. One publisher against its own earlier self is the
 * opposite: it is the only comparison a single survey can support.
 */

/** Current, then previous, then older -- the curve overlay's own colour order. */
const SERIES_CLASS = [
  styles.releaseCurrent,
  styles.releasePrior,
  styles.releaseOlder,
];

type Row = {
  at: number;
  horizon: string;
  median: number;
  p25: number | null;
  p75: number | null;
  respondents: number | null;
};

type Series = {
  path: PolicyPath;
  label: string;
  className: string;
  rows: Row[];
};

/** "Jun. 16-17 2026" -> "Jun 26"; "2027 Q2" -> "27Q2"; "2029" -> "2029". */
export function shortHorizon(horizon: string): string {
  const quarter = horizon.match(/^(\d{4})\s*Q([1-4])$/);
  if (quarter) return `${quarter[1].slice(2)}Q${quarter[2]}`;
  const meeting = horizon.match(/^([A-Za-z]{3})[a-z]*\.?\s.*?(\d{4})$/);
  if (meeting) return `${meeting[1]} ${meeting[2].slice(2)}`;
  return horizon;
}

function toRows(points: MacroPolicyPathPoint[]): Row[] {
  return (
    points
      .map((point) => ({
        at: point.horizon_date ? Date.parse(point.horizon_date) : Number.NaN,
        horizon: point.horizon,
        median: toFiniteNumber(point.rate_percent, Number.NaN),
        p25: finiteOrNull(point.p25_percent),
        p75: finiteOrNull(point.p75_percent),
        respondents: finiteOrNull(point.respondent_count),
      }))
      // A point without a horizon date has no place on a time axis. Dropping it is
      // the only alternative to inventing a position for it.
      .filter((row) => Number.isFinite(row.median) && Number.isFinite(row.at))
      .sort((left, right) => left.at - right.at)
  );
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
    : `Respondents by horizon: ${lo}–${hi}.`;
}

/** Year starts inside the plotted range, so the axis is dated rather than ordinal. */
function yearTicks(from: number, to: number): { at: number; label: string }[] {
  const first = new Date(from).getUTCFullYear();
  const last = new Date(to).getUTCFullYear();
  const ticks: { at: number; label: string }[] = [];
  for (let year = first; year <= last; year += 1) {
    const at = Date.UTC(year, 0, 1);
    if (at >= from && at <= to) ticks.push({ at, label: String(year) });
  }
  return ticks;
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
          The release parsed, but carried no dated expectation to place on a
          time axis.
        </p>
      </div>
    );
  }

  const series: Series[] = [
    {
      path,
      label: `${releaseDate(path)} survey`,
      className: SERIES_CLASS[0],
      rows,
    },
    ...priorReleases(slot)
      .slice(0, SERIES_CLASS.length - 1)
      .map((earlier, index) => ({
        path: earlier,
        label: `${releaseDate(earlier)} survey`,
        className: SERIES_CLASS[index + 1],
        rows: toRows(earlier.points ?? []),
      }))
      .filter((item) => item.rows.length > 0),
  ];

  const everyRow = series.flatMap((item) => item.rows);
  const values = everyRow.flatMap((row) =>
    [row.median, row.p25, row.p75].filter((n): n is number => n != null),
  );
  const lo = Math.min(...values) - 0.15;
  const hi = Math.max(...values) + 0.15;
  const span = Math.max(hi - lo, 0.5);

  const from = Math.min(...everyRow.map((row) => row.at));
  const to = Math.max(...everyRow.map((row) => row.at));
  const range = Math.max(to - from, 1);

  const xFor = (at: number) => PAD_LEFT + ((at - from) / range) * PLOT_W;
  const yFor = (value: number) => PAD_TOP + (1 - (value - lo) / span) * PLOT_H;

  // The band is drawn only across the run where both quartiles exist, so a gap in the
  // publisher's dispersion shows as a gap rather than as a straight interpolation.
  // Current release only: three overlapping bands would hide every one of them.
  const banded = rows.filter((row) => row.p25 != null && row.p75 != null);
  const bandPoints = banded.length
    ? [
        ...banded.map((row) => `${xFor(row.at)},${yFor(row.p75 as number)}`),
        ...banded
          .slice()
          .reverse()
          .map((row) => `${xFor(row.at)},${yFor(row.p25 as number)}`),
      ].join(" ")
    : "";

  const ticks = axisTicks(lo, span);
  const dateTicks = yearTicks(from, to);

  return (
    <div className={styles.pathChartBlock}>
      <BoardRead>
        Full dealer path and release history; no committee or market series.
      </BoardRead>
      <div className={`${styles.chartPanel} chart`} aria-label="Dealer expectations chart">
        <div className={styles.chartHeader}>
          <strong>Expected policy rate by meeting date</strong>
          <div className={`${styles.chartLegend} lgd`}>
            {series.map((item) => (
              <span key={item.path.source_record_id}>
                <i className={item.className} />
                {item.label}
              </span>
            ))}
            <span>
              <i className={styles.dealerBandSwatch} />
              IQR (latest)
            </span>
          </div>
        </div>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label="New York Fed Survey of Market Expectations: median expected policy rate by meeting date, latest survey with interquartile range and the surveys before it"
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

          {dateTicks.map((tick) => (
            <g key={tick.label}>
              <line
                x1={xFor(tick.at)}
                x2={xFor(tick.at)}
                y1={PAD_TOP}
                y2={PAD_TOP + PLOT_H}
                stroke="var(--border-dim)"
                strokeDasharray="3 5"
              />
              <text
                x={xFor(tick.at)}
                y={X_LABEL_NEAR}
                textAnchor="middle"
                className={styles.svgLabel}
              >
                {tick.label}
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

          {/* Oldest first so the current survey is drawn last and reads on top. */}
          {series
            .slice()
            .reverse()
            .map((item) => (
              <polyline
                key={item.path.source_record_id}
                points={item.rows
                  .map((row) => `${xFor(row.at)},${yFor(row.median)}`)
                  .join(" ")}
                fill="none"
                className={item.className}
                data-testid={
                  item === series[0]
                    ? "dealer-path-median"
                    : "dealer-path-median-prior"
                }
                strokeWidth={item === series[0] ? 3 : 2}
                strokeDasharray={item === series[0] ? undefined : "6 4"}
                strokeLinejoin="round"
                strokeLinecap="round"
              />
            ))}

          {rows.map((row) => (
            <circle
              key={`${row.horizon}:${row.at}`}
              cx={xFor(row.at)}
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
          ))}
        </svg>
      </div>

      <p className="cap">
        {path.source} · released {releaseDate(path)}
        {series.length > 1
          ? ` · ${series.length - 1} earlier survey${series.length > 2 ? "s" : ""} overlaid`
          : ""}
      </p>
      <div className="grid g2">
        <BoardRead testId="dealer-path-note">
          {respondentNote(rows)} Dated points show when the survey first moves.
        </BoardRead>
        <BoardRead>
          {series.length > 1
            ? "Earlier surveys are overlaid as separate releases."
            : "Only one survey has been ingested, so a revision comparison is not available yet."}{" "}
          Never averaged with Fed projections.
        </BoardRead>
      </div>
    </div>
  );
}
