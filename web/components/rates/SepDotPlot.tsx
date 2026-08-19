import styles from "./RatesDesk.module.css";
import { finiteOrNull, toFiniteNumber } from "./format";
import { plottable, releaseDate } from "./policyPath";
import type { MacroPolicyPathPoint, PolicyPathSlot } from "./types";

/**
 * The SEP as the committee publishes it: a dot plot.
 *
 * The list this replaces printed a median and a dot count, which is the one reading of
 * the SEP that hides what it is for -- eighteen participants disagreeing. A median of
 * 3.60% carries the same text whether every dot sits on it or they span 2.875 to 4.375,
 * and those are different worlds for a rates desk.
 *
 * Every dot is anonymous, here as in the release. The plot deliberately has no way to
 * express which participant a dot belongs to, because the FOMC does not publish it.
 */

const WIDTH = 780;
const HEIGHT = 400;
const PAD_LEFT = 56;
const PAD_RIGHT = 24;
const PAD_TOP = 26;
const PAD_BOTTOM = 52;
const PLOT_W = WIDTH - PAD_LEFT - PAD_RIGHT;
const PLOT_H = HEIGHT - PAD_TOP - PAD_BOTTOM;
const DOT_R = 4.5;
const DOT_GAP = 12;

type Dot = { rate: number; count: number };

function dotsOf(point: MacroPolicyPathPoint): Dot[] {
  return (point.participant_distribution ?? [])
    .map((entry) => ({
      rate: toFiniteNumber(entry.rate_percent, Number.NaN),
      count: entry.participant_count,
    }))
    .filter((dot) => Number.isFinite(dot.rate) && dot.count > 0);
}

export function SepDotPlot({
  slot,
}: {
  slot: PolicyPathSlot | null | undefined;
}) {
  const resolved = plottable(slot);
  if (resolved.status === "empty") {
    return (
      <div className={styles.stateMissing} data-testid="sep-dot-plot-missing">
        <strong>No committee projection to plot</strong>
        <p>{resolved.reason}</p>
      </div>
    );
  }

  const path = resolved.path;
  const points = path.points ?? [];
  const columns = points.map((point) => ({ point, dots: dotsOf(point) }));
  const values = columns.flatMap((column) => [
    ...column.dots.map((dot) => dot.rate),
    ...[
      finiteOrNull(column.point.rate_percent),
      finiteOrNull(column.point.central_tendency_lower_percent),
      finiteOrNull(column.point.central_tendency_upper_percent),
    ].filter((n): n is number => n != null),
  ]);

  if (!values.length) {
    return (
      <div className={styles.stateMissing} data-testid="sep-dot-plot-missing">
        <strong>No committee projection to plot</strong>
        <p>
          The release parsed, but carried no numeric projection to place on an
          axis.
        </p>
      </div>
    );
  }

  // Pad the domain so the extreme dots are not drawn on the frame.
  const lo = Math.min(...values) - 0.2;
  const hi = Math.max(...values) + 0.2;
  const span = Math.max(hi - lo, 0.5);
  const colW = PLOT_W / Math.max(columns.length, 1);

  const yFor = (rate: number) => PAD_TOP + (1 - (rate - lo) / span) * PLOT_H;
  const xFor = (index: number) => PAD_LEFT + colW * (index + 0.5);

  const ticks = Array.from({ length: 6 }, (_, i) => lo + (span * i) / 5);
  // Deliberately the per-horizon maximum, not the sum: summing the columns produces a
  // number ("71") that reads as a participant count and is not one. Columns can differ
  // -- a participant who submitted no 2028 dot leaves that column one short -- so the
  // fullest column is the panel size and the shortfall shows in the per-column labels.
  const dotsPerColumn = columns.map((column) =>
    column.dots.reduce((n, dot) => n + dot.count, 0),
  );
  const participants = dotsPerColumn.length ? Math.max(...dotsPerColumn) : 0;

  return (
    <div className={styles.pathChartBlock}>
      <div className={styles.chartPanel} aria-label="SEP dot plot">
        <div className={styles.chartHeader}>
          <strong>Participant projections · {participants} participants</strong>
          <div className={styles.chartLegend}>
            <span>
              <i className={styles.sepDotSwatch} />
              One participant
            </span>
            <span>
              <i className={styles.sepMedianSwatch} />
              Median
            </span>
            <span>
              <i className={styles.sepBandSwatch} />
              Central tendency
            </span>
          </div>
        </div>
        <svg
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          role="img"
          aria-label={`FOMC Summary of Economic Projections dot plot, up to ${participants} anonymous participant projections per horizon`}
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

          {columns.map((column, index) => {
            const cx = xFor(index);
            const lower = finiteOrNull(column.point.central_tendency_lower_percent);
            const upper = finiteOrNull(column.point.central_tendency_upper_percent);
            const median = finiteOrNull(column.point.rate_percent);
            const half = colW * 0.36;
            return (
              <g key={`${column.point.horizon}:${index}`}>
                {lower != null && upper != null ? (
                  <rect
                    x={cx - half}
                    y={yFor(upper)}
                    width={half * 2}
                    height={Math.max(yFor(lower) - yFor(upper), 1)}
                    className={styles.sepBand}
                  >
                    <title>{`Central tendency ${lower.toFixed(2)}–${upper.toFixed(2)}%`}</title>
                  </rect>
                ) : null}

                {column.dots.map((dot) =>
                  // Spread a level's dots symmetrically about the column centre. The
                  // count is the fact; the horizontal position carries no meaning and
                  // no identity.
                  Array.from({ length: dot.count }, (_, i) => {
                    const offset = (i - (dot.count - 1) / 2) * DOT_GAP;
                    return (
                      <circle
                        key={`${dot.rate}:${i}`}
                        cx={cx + offset}
                        cy={yFor(dot.rate)}
                        r={DOT_R}
                        className={styles.sepDot}
                      >
                        <title>{`${dot.count} participant${dot.count === 1 ? "" : "s"} at ${dot.rate.toFixed(3)}% (anonymous)`}</title>
                      </circle>
                    );
                  }),
                )}

                {median != null ? (
                  <g>
                    <line
                      x1={cx - half}
                      x2={cx + half}
                      y1={yFor(median)}
                      y2={yFor(median)}
                      className={styles.sepMedian}
                    />
                    <text
                      x={cx + half + 4}
                      y={yFor(median) - 6}
                      textAnchor="end"
                      className={styles.sepMedianLabel}
                    >
                      {median.toFixed(2)}%
                    </text>
                  </g>
                ) : null}

                <text
                  x={cx}
                  y={HEIGHT - 26}
                  textAnchor="middle"
                  className={styles.svgAxisLabel}
                >
                  {column.point.horizon}
                </text>
                <text
                  x={cx}
                  y={HEIGHT - 11}
                  textAnchor="middle"
                  className={styles.svgLabel}
                >
                  {column.dots.reduce((n, dot) => n + dot.count, 0)} dots
                </text>
              </g>
            );
          })}
        </svg>
      </div>

      <p className={styles.pathProvenance}>
        {path.source} · released {releaseDate(path)}
      </p>
      {/* The dot plot is published without names. Attaching one -- the Chair's above
          all -- would invent a fact the FOMC deliberately does not publish. */}
      <p className={styles.pathNote} data-testid="sep-plot-anonymity-note">
        SEP dots are anonymous. Dot position within a year is spacing, not
        identity, and no dot on this chart is attributed to a named participant.
      </p>
    </div>
  );
}
