import type { components } from "@/lib/types";

import { finiteDomain, linearScale } from "@/lib/svgChart";

type Row = components["schemas"]["GoldDecompositionRow"];

const lensColor: Record<string, string> = {
  L1: "var(--positive, #05ad98)",
  L2: "var(--info, #3a8fd6)",
  L3: "var(--warning, #f5a623)",
};

type Props = {
  rows: Row[];
  width?: number;
  rowHeight?: number;
};

export function DecompositionBars({
  rows,
  width = 480,
  rowHeight = 22,
}: Props) {
  if (rows.length === 0) {
    return (
      <div
        style={{
          color: "var(--text-muted, #6b7280)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          padding: 12,
        }}
      >
        No decomposition data — lens cards have not yet exposed z-scores.
      </div>
    );
  }
  const values = rows.map((r) => Number(r.contribution));
  const domain = finiteDomain(values);
  const range: [number, number] = [-(width / 2 - 80), width / 2 - 80];
  const center = width / 2;
  const xScale = domain
    ? linearScale(
        [
          -Math.max(Math.abs(domain.lo), Math.abs(domain.hi)),
          Math.max(Math.abs(domain.lo), Math.abs(domain.hi)),
        ],
        range,
      )
    : null;
  const height = rows.length * rowHeight + 10;

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${width} ${height}`}
      style={{ display: "block" }}
    >
      <line
        x1={center}
        x2={center}
        y1={0}
        y2={height}
        stroke="var(--border-dim, #1b2030)"
        strokeWidth={0.5}
      />
      {rows.map((row, i) => {
        const v = Number(row.contribution);
        const x = xScale ? xScale(v) : center;
        const y = i * rowHeight + 4;
        const color = lensColor[row.lens] ?? "var(--text-secondary, #9aa3b2)";
        return (
          <g key={`${row.lens}-${row.factor}`}>
            <text
              x={8}
              y={y + rowHeight / 2 + 4}
              fontFamily="var(--font-mono)"
              fontSize={10}
              letterSpacing={1.2}
              fill="var(--text-muted, #6b7280)"
            >
              {row.lens}
            </text>
            <text
              x={40}
              y={y + rowHeight / 2 + 4}
              fontFamily="var(--font-mono)"
              fontSize={10}
              fill="var(--text-secondary, #9aa3b2)"
            >
              {row.factor}
            </text>
            <rect
              x={Math.min(center, x)}
              y={y + 4}
              width={Math.abs(x - center)}
              height={rowHeight - 10}
              fill={color}
              opacity={0.8}
            />
            <text
              x={x + (v >= 0 ? 6 : -6)}
              y={y + rowHeight / 2 + 4}
              textAnchor={v >= 0 ? "start" : "end"}
              fontFamily="var(--font-mono)"
              fontSize={10}
              fill={color}
            >
              {v >= 0 ? "+" : ""}
              {v.toFixed(2)}
            </text>
          </g>
        );
      })}
    </svg>
  );
}
