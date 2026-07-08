import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";

/** Tiny inline history line for a single technicals metric. Null-safe (a
 * single null never poisons the domain) and draws a faint zero baseline when
 * the domain straddles 0, so signed metrics read correctly. */
export function MetricSparkline({
  values,
  color = "var(--accent-vivid)",
  width = 132,
  height = 30,
}: {
  values: Array<number | null>;
  color?: string;
  width?: number;
  height?: number;
}) {
  const dom = finiteDomain(values);
  if (!dom) return null;
  const n = values.length;
  const x = linearScale([0, Math.max(1, n - 1)], [1, width - 1]);
  const y = linearScale([dom.lo, dom.hi], [height - 2, 2]);
  const pts = values.map((v, i) =>
    v == null ? null : ([x(i), y(v)] as [number, number]),
  );
  const showZero = dom.lo < 0 && dom.hi > 0;
  return (
    <svg
      viewBox={`0 0 ${width} ${height}`}
      width="100%"
      height={height}
      role="img"
      style={{ display: "block", marginTop: 6, overflow: "visible" }}
      preserveAspectRatio="none"
    >
      {showZero && (
        <line
          x1={0}
          x2={width}
          y1={y(0)}
          y2={y(0)}
          stroke="var(--border-dim)"
          strokeWidth={0.5}
          strokeDasharray="2 2"
        />
      )}
      <path
        d={pathFromNullablePoints(pts)}
        fill="none"
        stroke={color}
        strokeWidth={1}
        vectorEffect="non-scaling-stroke"
      />
    </svg>
  );
}
