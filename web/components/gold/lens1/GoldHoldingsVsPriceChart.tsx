import type { components } from "@/lib/types";

import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

// niceTicks is designed for "nice" numeric ranges (10, 50, 100), not millisecond
// timestamps — handing it a 13-month range produces ~34 ticks. For time axes we
// sample N evenly-spaced positions across the domain instead.
function sampledTimeTicks(lo: number, hi: number, count: number): number[] {
  if (count < 2 || hi <= lo) return [lo];
  const out: number[] = [];
  for (let i = 0; i < count; i += 1) {
    out.push(lo + ((hi - lo) * i) / (count - 1));
  }
  return out;
}

function fmtDateTick(ms: number): string {
  const d = new Date(ms);
  const y = d.getUTCFullYear();
  const m = String(d.getUTCMonth() + 1).padStart(2, "0");
  return `${y}-${m}`;
}

function fmtPriceTick(v: number): string {
  if (Math.abs(v) >= 1000) return v.toFixed(0);
  if (Math.abs(v) >= 10) return v.toFixed(1);
  return v.toFixed(2);
}

function fmtOzTick(v: number): string {
  // GLD holdings_oz is a large number (oz). Show in millions with one decimal.
  const m = v / 1_000_000;
  return `${m.toFixed(1)}M`;
}

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
  const goldYScale = goldDomain
    ? linearScale([goldDomain.lo, goldDomain.hi], yRange)
    : null;
  const gldYScale = gldDomain
    ? linearScale([gldDomain.lo, gldDomain.hi], yRange)
    : null;

  const goldPoints: Point[] = goldYScale
    ? goldHistory.map((p) => [
        xScale(new Date(p.obs_date).getTime()),
        goldYScale(toNumber(p.value)),
      ])
    : [];

  const gldPoints: Point[] = gldYScale
    ? gldHistory.map((p) => [
        xScale(new Date(p.obs_date).getTime()),
        gldYScale(toNumber(p.value)),
      ])
    : [];

  const xTicks = sampledTimeTicks(dateDomain.lo, dateDomain.hi, 6);
  const goldYTicks = goldDomain
    ? niceTicks(goldDomain.lo, goldDomain.hi, 4)
    : [];
  const gldYTicks = gldDomain ? niceTicks(gldDomain.lo, gldDomain.hi, 4) : [];

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
            {fmtDateTick(t)}
          </text>
        ))}
        {goldYScale &&
          goldYTicks.map((v) => (
            <g key={`yl-gold-${v}`}>
              <line
                x1={padding.left - 3}
                x2={padding.left}
                y1={goldYScale(v)}
                y2={goldYScale(v)}
                stroke="var(--text-muted, #6b7280)"
                strokeWidth={0.5}
              />
              <text
                x={padding.left - 6}
                y={goldYScale(v) + 3}
                textAnchor="end"
                fill="var(--positive, #05ad98)"
              >
                {fmtPriceTick(v)}
              </text>
            </g>
          ))}
        {gldYScale &&
          gldYTicks.map((v) => (
            <g key={`yl-gld-${v}`}>
              <line
                x1={padding.left + innerW}
                x2={padding.left + innerW + 3}
                y1={gldYScale(v)}
                y2={gldYScale(v)}
                stroke="var(--text-muted, #6b7280)"
                strokeWidth={0.5}
              />
              <text
                x={padding.left + innerW + 6}
                y={gldYScale(v) + 3}
                textAnchor="start"
                fill="var(--warning, #f5a623)"
              >
                {fmtOzTick(v)}
              </text>
            </g>
          ))}
        <text x={padding.left} y={10} fill="var(--positive, #05ad98)">
          GLD ($)
        </text>
        {gldYScale && (
          <text x={padding.left + 60} y={10} fill="var(--warning, #f5a623)">
            GLD (oz held)
          </text>
        )}
      </g>
    </svg>
  );
}
