import { useMemo } from "react";
import type React from "react";

export type ChartPoint = {
  x: number;
  y: number | null;
};

export type ChartSeries = {
  label: string;
  color: string;
  points: ChartPoint[];
};

export type NormalizedChartSeries = {
  label: string;
  color: string;
  points: Array<{ x: number; y: number }>;
};

export function normalizeChartSeries(
  series: ChartSeries[],
  assumeSorted = false,
): NormalizedChartSeries[] {
  return series.map((item) => ({
    ...item,
    points: (
      assumeSorted
        ? item.points
            .filter((point) => Number.isFinite(point.x) && point.y != null)
            .map((point) => ({ x: point.x, y: point.y as number }))
        : item.points
            .filter((point) => Number.isFinite(point.x) && point.y != null)
            .map((point) => ({ x: point.x, y: point.y as number }))
            .sort((a, b) => a.x - b.x)
    ),
  }));
}

export function MultiLineChart({
  series,
  height = 190,
  showZero = true,
  band,
  xLabel,
  assumeSorted = false,
}: {
  series: ChartSeries[];
  height?: number;
  showZero?: boolean;
  band?: { min: number; max: number; color: string };
  xLabel?: (x: number) => string;
  assumeSorted?: boolean;
}) {
  const cleanSeries = useMemo(
    () => normalizeChartSeries(series, assumeSorted),
    [series, assumeSorted],
  );
  const all = cleanSeries.flatMap((item) => item.points);
  if (!all.length) {
    return <div style={emptyChartStyle}>NO DATA</div>;
  }

  const width = 640;
  const top = 16;
  const right = 18;
  const bottom = 26;
  const left = 44;
  const innerW = width - left - right;
  const innerH = height - top - bottom;
  const xs = all.map((point) => point.x);
  const ys = all.flatMap((point) => [point.y]);
  if (showZero) ys.push(0);
  if (band) ys.push(band.min, band.max);
  const minX = Math.min(...xs);
  const maxX = Math.max(...xs);
  const rawMinY = Math.min(...ys);
  const rawMaxY = Math.max(...ys);
  const yPad = Math.max((rawMaxY - rawMinY) * 0.12, 0.01);
  const minY = rawMinY - yPad;
  const maxY = rawMaxY + yPad;

  const xScale = (x: number) =>
    left + ((x - minX) / Math.max(maxX - minX, 1)) * innerW;
  const yScale = (y: number) =>
    top + (1 - (y - minY) / Math.max(maxY - minY, 0.01)) * innerH;
  const pathFor = (points: { x: number; y: number }[]) =>
    points.map((point) => `${xScale(point.x)},${yScale(point.y)}`).join(" ");

  return (
    <div>
      <svg
        role="img"
        viewBox={`0 0 ${width} ${height}`}
        style={{ display: "block", width: "100%", height }}
      >
        <rect
          x={left}
          y={top}
          width={innerW}
          height={innerH}
          fill="rgba(255,255,255,0.015)"
          stroke="var(--border-dim)"
        />
        {band ? (
          <rect
            x={left}
            y={yScale(band.max)}
            width={innerW}
            height={Math.max(yScale(band.min) - yScale(band.max), 1)}
            fill={band.color}
          />
        ) : null}
        {showZero && minY < 0 && maxY > 0 ? (
          <line
            x1={left}
            x2={width - right}
            y1={yScale(0)}
            y2={yScale(0)}
            stroke="var(--border-dim)"
            strokeDasharray="4 4"
          />
        ) : null}
        {[0.25, 0.5, 0.75].map((ratio) => (
          <line
            key={ratio}
            x1={left}
            x2={width - right}
            y1={top + innerH * ratio}
            y2={top + innerH * ratio}
            stroke="rgba(148,163,184,0.14)"
          />
        ))}
        {cleanSeries.map((item) => (
          <polyline
            key={item.label}
            points={pathFor(item.points)}
            fill="none"
            stroke={item.color}
            strokeWidth={2}
            strokeLinejoin="round"
            strokeLinecap="round"
          />
        ))}
        <text x={left} y={height - 8} fill="var(--text-muted)" fontSize="10">
          {xLabel ? xLabel(minX) : String(minX)}
        </text>
        <text
          x={width - right}
          y={height - 8}
          fill="var(--text-muted)"
          fontSize="10"
          textAnchor="end"
        >
          {xLabel ? xLabel(maxX) : String(maxX)}
        </text>
        <text x={6} y={top + 4} fill="var(--text-muted)" fontSize="10">
          {maxY.toFixed(2)}
        </text>
        <text x={6} y={top + innerH} fill="var(--text-muted)" fontSize="10">
          {minY.toFixed(2)}
        </text>
      </svg>
      <div style={legendStyle}>
        {series.map((item) => (
          <span key={item.label} style={legendItemStyle}>
            <span style={{ ...swatchStyle, background: item.color }} />
            {item.label}
          </span>
        ))}
      </div>
    </div>
  );
}

export const panelStyle: React.CSSProperties = {
  border: "1px solid var(--border-dim)",
  background: "var(--bg-panel)",
  padding: 16,
};

export const panelTitleStyle: React.CSSProperties = {
  color: "var(--text-primary)",
  fontFamily: "var(--font-mono)",
  fontSize: 14,
  fontWeight: 800,
  letterSpacing: 0,
  margin: "0 0 12px",
};

export const labelStyle: React.CSSProperties = {
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  letterSpacing: 1.2,
  textTransform: "uppercase",
};

export const tableStyle: React.CSSProperties = {
  width: "100%",
  borderCollapse: "collapse",
  color: "var(--text-secondary)",
  fontSize: 12,
};

export const thStyle: React.CSSProperties = {
  borderBottom: "1px solid var(--border-dim)",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  fontWeight: 700,
  padding: "8px 6px",
  textAlign: "left",
  textTransform: "uppercase",
};

export const tdStyle: React.CSSProperties = {
  borderBottom: "1px solid rgba(148,163,184,0.12)",
  padding: "8px 6px",
  verticalAlign: "top",
};

export const emptyChartStyle: React.CSSProperties = {
  display: "grid",
  minHeight: 170,
  placeItems: "center",
  border: "1px dashed var(--border-dim)",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};

const legendStyle: React.CSSProperties = {
  display: "flex",
  flexWrap: "wrap",
  gap: 12,
  marginTop: 8,
  color: "var(--text-secondary)",
  fontFamily: "var(--font-mono)",
  fontSize: 11,
};

const legendItemStyle: React.CSSProperties = {
  display: "inline-flex",
  alignItems: "center",
  gap: 6,
};

const swatchStyle: React.CSSProperties = {
  display: "inline-block",
  width: 9,
  height: 9,
};
