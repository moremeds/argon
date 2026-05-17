import type { components } from "@/lib/types";

import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

type Hp = components["schemas"]["GoldHistoryPoint"];

type Props = {
  goldHistory: Hp[];
  gldHistory: Hp[];
  width?: number;
  height?: number;
};

function toNumber(v: string | number): number {
  return typeof v === "string" ? Number(v) : v;
}

export function GoldHoldingsVsPriceChart({
  goldHistory,
  gldHistory,
  width = 640,
  height = 200,
}: Props) {
  if (goldHistory.length === 0 && gldHistory.length === 0) {
    return (
      <div
        style={{
          color: "var(--text-muted, #6b7280)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          padding: 12,
        }}
      >
        No history yet
      </div>
    );
  }

  const padding = { top: 12, right: 56, bottom: 24, left: 48 };
  const innerW = width - padding.left - padding.right;
  const innerH = height - padding.top - padding.bottom;

  const allDates = [...goldHistory, ...gldHistory].map((p) =>
    new Date(p.obs_date).getTime(),
  );
  const dateDomain = finiteDomain(allDates);
  const goldDomain = finiteDomain(goldHistory.map((p) => toNumber(p.value)));
  const gldDomain = finiteDomain(gldHistory.map((p) => toNumber(p.value)));
  const xRange: [number, number] = [padding.left, padding.left + innerW];
  const yRange: [number, number] = [padding.top + innerH, padding.top];

  if (dateDomain == null || dateDomain.count < 2) {
    return null;
  }

  const xScale = linearScale([dateDomain.lo, dateDomain.hi], xRange);

  const goldPoints: Point[] = goldDomain
    ? goldHistory.map((p) => [
        xScale(new Date(p.obs_date).getTime()),
        linearScale([goldDomain.lo, goldDomain.hi], yRange)(toNumber(p.value)),
      ])
    : [];

  const gldPoints: Point[] = gldDomain
    ? gldHistory.map((p) => [
        xScale(new Date(p.obs_date).getTime()),
        linearScale([gldDomain.lo, gldDomain.hi], yRange)(toNumber(p.value)),
      ])
    : [];

  const xTicks = niceTicks(dateDomain.lo, dateDomain.hi, 5);

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block" }}
    >
      <g>
        {xTicks.map((t) => (
          <line
            key={t}
            x1={xScale(t)}
            x2={xScale(t)}
            y1={padding.top}
            y2={padding.top + innerH}
            stroke="var(--chart-grid, #1e2230)"
            strokeWidth={0.5}
          />
        ))}
      </g>
      {goldPoints.length > 0 && (
        <path
          d={pathFromPoints(goldPoints)}
          fill="none"
          stroke="var(--positive, #05ad98)"
          strokeWidth={1.5}
        />
      )}
      {gldPoints.length > 0 && (
        <path
          d={pathFromPoints(gldPoints)}
          fill="none"
          stroke="var(--warning, #f5a623)"
          strokeWidth={1.5}
          strokeDasharray="4 2"
        />
      )}
      <g
        fontFamily="var(--font-mono)"
        fontSize={9}
        fill="var(--text-muted, #6b7280)"
      >
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
        <text x={padding.left} y={10} fill="var(--positive, #05ad98)">
          GOLD (USD/oz)
        </text>
        <text x={padding.left + 120} y={10} fill="var(--warning, #f5a623)">
          GLD (oz held)
        </text>
      </g>
    </svg>
  );
}
