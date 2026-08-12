import type { Point } from "@/lib/svgChart";
import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";

export type ComponentSeries = {
  key: string;
  label: string;
  role: string;
  values: (number | null)[];
};

const INPUT_FILLS = [
  "var(--accent-bg)",
  "var(--accent-warm)",
  "var(--accent-vol)",
];

/**
 * Grouped bars for a feature's components, with its ratio as a line.
 *
 * Hand-rolled SVG per the repo's charting rule — `lightweight-charts` has two
 * documented exceptions and a static bar series is not one of them.
 *
 * Three choices that carry meaning rather than style:
 *
 * - **Context series are visually subordinate.** A `context` field is shown
 *   because it is informative, not because the ratio uses it. Rendering it like
 *   an input would imply it reconciles with the line, and it does not.
 * - **A null is a gap, never a zero bar.** Zero is a figure; absence is not.
 * - **The ratio stroke is caller-supplied.** Three of the seven features have no
 *   validated direction, so this component must not choose a colour that implies
 *   one — see FEATURE_DIRECTION in fundamentals/features.py.
 */
export function FundamentalBarChart({
  series,
  ratio,
  periods,
  ratioUnit,
  ratioStroke = "var(--text-secondary)",
  width = 640,
  height = 220,
}: {
  series: ComponentSeries[];
  ratio: (number | null)[];
  periods: string[];
  ratioUnit: "ratio" | "turns";
  ratioStroke?: string;
  width?: number;
  height?: number;
}) {
  const PAD = { top: 12, right: 46, bottom: 22, left: 52 };
  const plotW = width - PAD.left - PAD.right;
  const plotH = height - PAD.top - PAD.bottom;

  // `finiteDomain(values)` takes ONE argument and returns `{lo, hi, count}` or
  // **null** when fewer than two finite values exist — it has no fallback
  // parameters. Both null cases are real here: a brand-new ticker has one
  // quarter, and a fully-suppressed feature has an all-null ratio.
  const bars = finiteDomain(series.flatMap((s) => s.values));
  const rat = finiteDomain(ratio);
  // Fewer than two finite bar values is a real state — a newly-covered ticker
  // with one quarter, or a fully-suppressed feature. Say so; returning null
  // would leave a silent blank that reads as a layout bug.
  if (!bars) {
    return (
      <div
        style={{ fontSize: 11, color: "var(--text-muted)", padding: "12px 0" }}
      >
        Not enough reported history to chart these components.
      </div>
    );
  }

  // `linearScale(domain, range)` takes two TUPLES, not four scalars.
  // Range is [plotH, 0] so larger values sit higher on screen.
  const yBar = linearScale([Math.min(0, bars.lo), bars.hi], [plotH, 0]);
  const yRatio = rat ? linearScale([rat.lo, rat.hi], [plotH, 0]) : null;

  const slot = plotW / Math.max(periods.length, 1);
  const barW = Math.max(2, (slot * 0.7) / Math.max(series.length, 1));

  // `Point` is a TUPLE `[x, y]`, and `pathFromNullablePoints` takes
  // `ReadonlyArray<Point | null>` — a null entry breaks the line into a new
  // subpath, which is exactly the gap behaviour we want.
  const ratioPoints: (Point | null)[] =
    yRatio == null
      ? []
      : ratio.map((v, i) =>
          v == null
            ? null
            : ([PAD.left + slot * (i + 0.5), PAD.top + yRatio(v)] as Point),
        );

  const fmtAxis = (v: number) =>
    ratioUnit === "ratio" ? `${(v * 100).toFixed(0)}%` : `${v.toFixed(1)}x`;

  return (
    <svg
      width={width}
      height={height}
      viewBox={`0 0 ${width} ${height}`}
      role="img"
      style={{ maxWidth: "100%", height: "auto" }}
    >
      <title>
        {series.map((s) => s.label).join(", ")} over {periods.length} quarters
      </title>

      {series.map((s, si) =>
        s.values.map((v, i) =>
          v == null ? null : (
            <rect
              key={`${s.key}-${i}`}
              data-series={s.key}
              data-role={s.role}
              x={PAD.left + slot * i + slot * 0.15 + barW * si}
              y={PAD.top + yBar(Math.max(v, 0))}
              width={barW}
              height={Math.abs(yBar(v) - yBar(0))}
              fill={
                s.role === "context"
                  ? "var(--text-muted)"
                  : INPUT_FILLS[si % INPUT_FILLS.length]
              }
              fillOpacity={s.role === "context" ? 0.35 : 0.85}
            />
          ),
        ),
      )}

      <path
        data-ratio=""
        d={pathFromNullablePoints(ratioPoints)}
        fill="none"
        stroke={ratioStroke}
        strokeWidth={1.5}
        // Required by `pathFromNullablePoints`: an isolated finite point between
        // two nulls is emitted as a zero-length segment, which renders as
        // nothing under the default butt cap. A ratio with a single reported
        // quarter surrounded by gaps is a real state for a thin filer.
        strokeLinecap="round"
      />

      {rat ? (
        <>
          <text
            x={width - PAD.right + 6}
            y={PAD.top + 4}
            fill="var(--text-muted)"
            fontSize={9}
          >
            {fmtAxis(rat.hi)}
          </text>
          <text
            x={width - PAD.right + 6}
            y={PAD.top + plotH}
            fill="var(--text-muted)"
            fontSize={9}
          >
            {fmtAxis(rat.lo)}
          </text>
        </>
      ) : null}

      <text x={2} y={PAD.top + 8} fill="var(--text-muted)" fontSize={9}>
        {(bars.hi / 1e9).toFixed(0)}B
      </text>
      <text x={2} y={PAD.top + plotH} fill="var(--text-muted)" fontSize={9}>
        0
      </text>

      <text x={PAD.left} y={height - 6} fill="var(--text-muted)" fontSize={9}>
        {periods[0]}
      </text>
      <text
        x={PAD.left + plotW}
        y={height - 6}
        textAnchor="end"
        fill="var(--text-muted)"
        fontSize={9}
      >
        {periods[periods.length - 1]}
      </text>
    </svg>
  );
}
