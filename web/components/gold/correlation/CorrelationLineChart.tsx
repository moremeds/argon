import type { components } from "@/lib/types";

import {
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

type Series = components["schemas"]["GoldCorrelationPoint"][];
type Band = components["schemas"]["GoldCorrelationBand"] | null | undefined;

type SeriesSpec = {
  id: string;
  label: string;
  color: string;
  points: Series;
};

type Props = {
  series: SeriesSpec[];
  pre2022Band?: Band;
  width?: number;
  height?: number;
};

function toNumber(v: string | number): number {
  return typeof v === "string" ? Number(v) : v;
}

export function CorrelationLineChart({
  series,
  pre2022Band,
  width = 640,
  height = 240,
}: Props) {
  const hasData = series.some((s) => s.points.length > 0);
  if (!hasData) {
    return (
      <div
        style={{
          color: "var(--text-muted, #6b7280)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          padding: 12,
        }}
      >
        No correlation history yet
      </div>
    );
  }

  const padding = { top: 12, right: 80, bottom: 28, left: 48 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;
  const xRange: [number, number] = [padding.left, padding.left + innerW];
  const yRange: [number, number] = [padding.top + innerH, padding.top];

  const allDates = series.flatMap((s) =>
    s.points.map((p) => new Date(p.obs_date).getTime()),
  );
  const minD = Math.min(...allDates);
  const maxD = Math.max(...allDates);
  const xScale = linearScale([minD, maxD], xRange);
  const yScale = linearScale([-1, 1], yRange); // correlation is bounded

  const xTicks = niceTicks(minD, maxD, 5);
  const yTicks = [-1, -0.5, 0, 0.5, 1];

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block" }}
      role="img"
      aria-label={`Rolling correlation of gold against ${series.map((s) => s.label).join(", ")}${pre2022Band ? ", with the pre-2022 reference band" : ""}`}
    >
      <g>
        {yTicks.map((t) => (
          <line
            key={t}
            x1={padding.left}
            x2={padding.left + innerW}
            y1={yScale(t)}
            y2={yScale(t)}
            stroke="var(--chart-grid, #1e2230)"
            strokeWidth={0.5}
          />
        ))}
      </g>
      {pre2022Band && (
        <rect
          x={padding.left}
          y={yScale(toNumber(pre2022Band.mean) + toNumber(pre2022Band.std))}
          width={innerW}
          height={Math.abs(
            yScale(toNumber(pre2022Band.mean) - toNumber(pre2022Band.std)) -
              yScale(toNumber(pre2022Band.mean) + toNumber(pre2022Band.std)),
          )}
          fill="var(--info, #3a8fd6)"
          opacity={0.08}
        />
      )}
      {series.map((s) => {
        const points: Point[] = s.points.map((p) => [
          xScale(new Date(p.obs_date).getTime()),
          yScale(toNumber(p.value)),
        ]);
        if (points.length === 0) return null;
        return (
          <path
            key={s.id}
            d={pathFromPoints(points)}
            fill="none"
            stroke={s.color}
            strokeWidth={1.5}
          />
        );
      })}
      <g
        fontFamily="var(--font-mono)"
        fontSize={9}
        fill="var(--text-muted, #6b7280)"
      >
        {yTicks.map((t) => (
          <text
            key={`yl-${t}`}
            x={padding.left - 6}
            y={yScale(t) + 3}
            textAnchor="end"
          >
            {t.toFixed(1)}
          </text>
        ))}
        {xTicks.map((t) => (
          <text
            key={`xl-${t}`}
            x={xScale(t)}
            y={height - padding.bottom + 14}
            textAnchor="middle"
          >
            {new Date(t).toISOString().slice(0, 7)}
          </text>
        ))}
        {series.map((s, i) => (
          <text
            key={`leg-${s.id}`}
            x={padding.left + i * 120}
            y={10}
            fill={s.color}
          >
            {s.label}
          </text>
        ))}
      </g>
    </svg>
  );
}
