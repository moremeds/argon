import { linearScale, pathFromNullablePoints } from "@/lib/svgChart";

/**
 * One feature's trajectory. Hand-rolled SVG per the repo's charting rule.
 *
 * Three deliberate choices, all about not overstating what we know:
 *
 * - **Gaps are drawn, not bridged.** A quarter whose input was flagged arrives as
 *   `null` and breaks the line (`pathFromNullablePoints`), then gets a marker so
 *   the absence is visible rather than an invisible kink. Interpolating across it
 *   would produce a smooth, confident, wrong chart.
 * - **One neutral colour, never a red/green ramp.** Three of the seven features
 *   have no validated direction, so "up" is not "good" and the chart must not say
 *   otherwise.
 * - **A zero line only when the series actually crosses zero.** `rev_growth` and
 *   `neg_net_debt_ebitda` go negative and the sign is the whole story there;
 *   drawing a zero baseline on a series that never approaches it is chart junk.
 */
export function FundamentalSparkline({
  values,
  dates,
  label,
  width = 220,
  height = 44,
  stroke = "var(--accent-bg)",
}: {
  values: (number | null)[];
  dates: string[];
  label: string;
  width?: number;
  height?: number;
  stroke?: string;
}) {
  const finite = values.filter(
    (v): v is number => v != null && Number.isFinite(v),
  );
  if (finite.length < 2) {
    return (
      <div
        style={{
          height,
          fontSize: 10,
          color: "var(--text-muted)",
          paddingTop: 14,
        }}
      >
        not enough history
      </div>
    );
  }

  const pad = 3;
  let lo = Math.min(...finite);
  let hi = Math.max(...finite);
  if (lo === hi) {
    // A flat series would divide by a zero span; give it a band so it renders
    // as a centred flat line rather than collapsing onto an edge.
    lo -= Math.abs(lo || 1) * 0.1;
    hi += Math.abs(hi || 1) * 0.1;
  }
  const x = linearScale([0, values.length - 1], [pad, width - pad]);
  const y = linearScale([lo, hi], [height - pad, pad]);

  const points = values.map((v, i) =>
    v == null || !Number.isFinite(v)
      ? null
      : ([x(i), y(v)] as [number, number]),
  );
  const gaps = values.map((v, i) => (v == null ? i : -1)).filter((i) => i >= 0);

  const lastIdx = points.reduce((acc, p, i) => (p ? i : acc), -1);
  const last = lastIdx >= 0 ? points[lastIdx] : null;
  const crossesZero = lo < 0 && hi > 0;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      preserveAspectRatio="none"
      role="img"
      aria-label={`${label}, ${finite.length} quarters from ${dates[0]} to ${dates[dates.length - 1]}`}
      style={{ display: "block", height, overflow: "visible" }}
    >
      <title>{`${label} · ${dates[0]} → ${dates[dates.length - 1]}`}</title>
      {crossesZero ? (
        <line
          x1={pad}
          x2={width - pad}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--border-dim)"
          strokeWidth={1}
        />
      ) : null}
      {gaps.map((i) => (
        <line
          key={i}
          x1={x(i)}
          x2={x(i)}
          y1={pad}
          y2={height - pad}
          stroke="var(--warning)"
          strokeWidth={1}
          strokeDasharray="2 2"
          opacity={0.55}
        />
      ))}
      <path
        d={pathFromNullablePoints(points)}
        fill="none"
        stroke={stroke}
        strokeWidth={1.5}
        // Required by pathFromNullablePoints: isolated points are emitted as
        // zero-length segments and only render with a round cap.
        strokeLinecap="round"
        strokeLinejoin="round"
      />
      {last ? <circle cx={last[0]} cy={last[1]} r={2} fill={stroke} /> : null}
    </svg>
  );
}
