"use client";

import { useEffect, useMemo, useRef, useState } from "react";
import { finiteDomain, linearScale } from "@/lib/svgChart";

export interface CriHistoryEntry {
  date: string;
  vix: number | null | undefined;
  vvix: number | null | undefined;
  spy?: number | null | undefined;
  cor1m?: number | null | undefined;
  realized_vol?: number | null | undefined;
  spx_vs_ma_pct?: number | null | undefined;
  vix_5d_roc?: number | null | undefined;
  vvix_5d_roc?: number | null | undefined;
  cor1m_5d_change?: number | null | undefined;
  // v3: tactical pullback feeds the prior-dot on the Trend Break component bar
  pullback_20d_pct?: number | null | undefined;
}

export interface ChartSeries {
  key: keyof CriHistoryEntry;
  label: string;
  color: string;
  axis: "left" | "right";
  format?: (v: number) => string;
}

interface CriHistoryChartProps {
  history: CriHistoryEntry[];
  series: [ChartSeries, ChartSeries];
  title: string;
  liveValues?: Partial<Record<keyof CriHistoryEntry, number>>;
}

const MARGIN = { top: 20, right: 56, bottom: 32, left: 48 };
const HEIGHT = 440;

function defaultFormat(v: number): string {
  return v.toFixed(2);
}

function pickVal(
  d: CriHistoryEntry,
  key: keyof CriHistoryEntry,
): number | null {
  const raw = d[key];
  if (raw == null) return null;
  if (typeof raw !== "number") return null;
  return Number.isFinite(raw) ? raw : null;
}

function fmtDateLabel(d: Date): string {
  const m = d.toLocaleString("en-US", { month: "short" });
  return `${m} ${d.getDate()}`;
}

export default function CriHistoryChart({
  history,
  series,
  title,
  liveValues,
}: CriHistoryChartProps) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(400);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(
    null,
  );

  useEffect(() => {
    const el = containerRef.current;
    if (!el) return;
    const ro = new ResizeObserver((entries) => {
      const e = entries[0];
      if (e) setWidth(e.contentRect.width);
    });
    ro.observe(el);
    setWidth(el.getBoundingClientRect().width);
    return () => ro.disconnect();
  }, []);

  // Merge live values into the last data point (for the live overlay dot).
  const chartData = useMemo<CriHistoryEntry[]>(() => {
    if (!history || history.length === 0) return [];
    if (!liveValues || Object.keys(liveValues).length === 0) return history;
    const out = [...history];
    const last = { ...out[out.length - 1] };
    for (const [k, v] of Object.entries(liveValues)) {
      if (v != null) (last as Record<string, unknown>)[k] = v;
    }
    out[out.length - 1] = last;
    return out;
  }, [history, liveValues]);

  const [leftSeries, rightSeries] = series;
  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;

  if (chartData.length < 2) {
    return (
      <div className="cri-history-chart-panel">
        <div
          className="section-header"
          style={{ marginBottom: 12, padding: 0 }}
        >
          <div className="section-title">{title}</div>
        </div>
        <div className="cri-history-chart-shell">
          <div className="chart-surface cri-history-chart-surface">
            <div
              className="chart-empty-state cri-history-chart-empty"
              data-testid="cri-history-chart-empty"
            >
              NO HISTORY AVAILABLE
            </div>
          </div>
        </div>
      </div>
    );
  }

  const dates = chartData.map((d) => new Date(d.date));
  const x = linearScale([0, chartData.length - 1], [0, innerW]);

  function buildY(s: ChartSeries) {
    const vals = chartData.map((d) => pickVal(d, s.key));
    const dom = finiteDomain(vals);
    if (!dom) return null;
    const pad = (dom.hi - dom.lo) * 0.15 || 2;
    return linearScale([dom.lo - pad, dom.hi + pad], [innerH, 0]);
  }

  const yLeft = buildY(leftSeries);
  const yRight = buildY(rightSeries);

  function pathFor(s: ChartSeries, y: ((v: number) => number) | null): string {
    if (!y) return "";
    const pts = chartData
      .map((d, i) => {
        const v = pickVal(d, s.key);
        return v == null ? null : ([x(i), y(v)] as [number, number]);
      })
      .filter((p): p is [number, number] => p != null);
    return pts
      .map(([px, py], i) => `${i === 0 ? "M" : "L"}${px},${py}`)
      .join(" ");
  }

  const leftPath = pathFor(leftSeries, yLeft);
  const rightPath = pathFor(rightSeries, yRight);

  function dotsFor(s: ChartSeries, y: ((v: number) => number) | null) {
    if (!y) return [];
    return chartData.flatMap((d, i) => {
      const v = pickVal(d, s.key);
      if (v == null) return [];
      return [{ cx: x(i), cy: y(v), i }];
    });
  }

  const leftDots = dotsFor(leftSeries, yLeft);
  const rightDots = dotsFor(rightSeries, yRight);

  // Grid ticks (5 evenly distributed on left axis range)
  const gridYs = yLeft
    ? Array.from({ length: 5 }, (_, k) => (innerH / 4) * k)
    : [];

  // For axis labels, recompute domain explicitly
  function domainOf(s: ChartSeries) {
    const vals = chartData.map((d) => pickVal(d, s.key));
    const dom = finiteDomain(vals);
    if (!dom) return null;
    const pad = (dom.hi - dom.lo) * 0.15 || 2;
    return { lo: dom.lo - pad, hi: dom.hi + pad };
  }
  const leftDom = domainOf(leftSeries);
  const rightDom = domainOf(rightSeries);

  function ticksFor(dom: { lo: number; hi: number } | null) {
    if (!dom) return [] as number[];
    const span = dom.hi - dom.lo || 1;
    const step = span / 4;
    return [0, 1, 2, 3, 4].map((k) => dom.lo + step * k);
  }

  const leftTicks = ticksFor(leftDom);
  const rightTicks = ticksFor(rightDom);

  // X tick dates — 5–7 evenly spaced
  const xTickCount = Math.max(2, Math.min(7, Math.floor(innerW / 80)));
  const xTickIdx = Array.from({ length: xTickCount }, (_, k) =>
    Math.round(((chartData.length - 1) * k) / (xTickCount - 1)),
  );

  // Hover handlers — snap to nearest index
  function onMove(e: React.MouseEvent<SVGRectElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const localX = e.clientX - rect.left - MARGIN.left;
    const frac = innerW > 0 ? localX / innerW : 0;
    let i = Math.round(frac * (chartData.length - 1));
    i = Math.max(0, Math.min(chartData.length - 1, i));
    setHoverIdx(i);
    setHoverPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }

  function onLeave() {
    setHoverIdx(null);
    setHoverPos(null);
  }

  const hoverEntry = hoverIdx != null ? chartData[hoverIdx] : null;
  const tooltipSide =
    hoverPos && hoverPos.x > width / 2
      ? { right: width - hoverPos.x + 12 }
      : { left: (hoverPos?.x ?? 0) + 12 };

  const leftFmt = leftSeries.format ?? defaultFormat;
  const rightFmt = rightSeries.format ?? defaultFormat;

  return (
    <div className="cri-history-chart-panel">
      <div
        className="section-header"
        style={{
          marginBottom: 12,
          padding: 0,
          display: "flex",
          alignItems: "center",
          justifyContent: "space-between",
        }}
      >
        <div className="section-title" style={{ padding: 0 }}>
          {title}
        </div>
        <div style={{ display: "flex", gap: 12 }}>
          {series.map((s) => (
            <div
              key={String(s.key)}
              style={{
                display: "flex",
                alignItems: "center",
                gap: 6,
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: "var(--text-muted)",
                textTransform: "uppercase",
                letterSpacing: "0.1em",
              }}
            >
              <span
                style={{
                  width: 10,
                  height: 2,
                  background: s.color,
                  display: "inline-block",
                }}
              />
              {s.label}
            </div>
          ))}
        </div>
      </div>

      <div ref={containerRef} className="cri-history-chart-shell">
        <div className="chart-surface cri-history-chart-surface">
          <svg
            ref={svgRef}
            className="cri-history-chart-svg"
            viewBox={`0 0 ${width} ${HEIGHT}`}
            role="img"
            aria-label={`${title} 20-session chart`}
            data-testid="cri-history-chart"
          >
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {/* Grid lines */}
              {gridYs.map((y, i) => (
                <line
                  key={i}
                  x1={0}
                  x2={innerW}
                  y1={y}
                  y2={y}
                  stroke="var(--chart-grid)"
                  strokeWidth={1}
                />
              ))}

              {/* Left series path + dots */}
              <path
                d={leftPath}
                fill="none"
                stroke={leftSeries.color}
                strokeWidth={2}
              />
              {leftDots.map((p) => (
                <circle
                  key={`l-${p.i}`}
                  cx={p.cx}
                  cy={p.cy}
                  r={2}
                  fill={leftSeries.color}
                  stroke="var(--bg-panel)"
                  strokeWidth={1}
                />
              ))}

              {/* Right series path + dots */}
              <path
                d={rightPath}
                fill="none"
                stroke={rightSeries.color}
                strokeWidth={2}
              />
              {rightDots.map((p) => (
                <circle
                  key={`r-${p.i}`}
                  cx={p.cx}
                  cy={p.cy}
                  r={2}
                  fill={rightSeries.color}
                  stroke="var(--bg-panel)"
                  strokeWidth={1}
                />
              ))}

              {/* Live overlay halo on the last point of each series */}
              {liveValues &&
                Object.keys(liveValues).length > 0 &&
                yLeft &&
                (() => {
                  const last = leftDots[leftDots.length - 1];
                  return last ? (
                    <circle
                      cx={last.cx}
                      cy={last.cy}
                      r={4}
                      fill={leftSeries.color}
                      stroke={leftSeries.color}
                      opacity={0.5}
                    />
                  ) : null;
                })()}
              {liveValues &&
                Object.keys(liveValues).length > 0 &&
                yRight &&
                (() => {
                  const last = rightDots[rightDots.length - 1];
                  return last ? (
                    <circle
                      cx={last.cx}
                      cy={last.cy}
                      r={4}
                      fill={rightSeries.color}
                      stroke={rightSeries.color}
                      opacity={0.5}
                    />
                  ) : null;
                })()}

              {/* Left axis ticks */}
              {leftTicks.map((v, i) => (
                <text
                  key={`lt-${i}`}
                  x={-8}
                  y={
                    (innerH * (leftTicks.length - 1 - i)) /
                    (leftTicks.length - 1)
                  }
                  textAnchor="end"
                  dominantBaseline="middle"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  fill={leftSeries.color}
                >
                  {leftFmt(v)}
                </text>
              ))}

              {/* Right axis ticks */}
              {rightTicks.map((v, i) => (
                <text
                  key={`rt-${i}`}
                  x={innerW + 8}
                  y={
                    (innerH * (rightTicks.length - 1 - i)) /
                    (rightTicks.length - 1)
                  }
                  textAnchor="start"
                  dominantBaseline="middle"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  fill={rightSeries.color}
                >
                  {rightFmt(v)}
                </text>
              ))}

              {/* X axis baseline */}
              <line
                x1={0}
                x2={innerW}
                y1={innerH}
                y2={innerH}
                stroke="var(--chart-axis)"
              />

              {/* X axis ticks */}
              {xTickIdx.map((i) => (
                <text
                  key={`xt-${i}`}
                  x={x(i)}
                  y={innerH + 18}
                  textAnchor="middle"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  fill="var(--chart-axis-muted)"
                >
                  {fmtDateLabel(dates[i])}
                </text>
              ))}

              {/* Hover crosshair */}
              {hoverEntry && hoverIdx != null && (
                <line
                  x1={x(hoverIdx)}
                  x2={x(hoverIdx)}
                  y1={0}
                  y2={innerH}
                  stroke="var(--border-dim)"
                  strokeDasharray="2 3"
                />
              )}

              {/* Invisible capture overlay */}
              <rect
                x={0}
                y={0}
                width={innerW}
                height={innerH}
                fill="transparent"
                onMouseMove={onMove}
                onMouseLeave={onLeave}
              />
            </g>
          </svg>
        </div>

        {hoverEntry && hoverPos && (
          <div
            className="chart-tooltip"
            style={{
              ...tooltipSide,
              top: hoverPos.y - 10,
            }}
          >
            <div className="chart-tooltip-date">{hoverEntry.date}</div>
            {series.map((s) => {
              const v = pickVal(hoverEntry, s.key);
              const f = s.format ?? defaultFormat;
              return (
                <div key={String(s.key)} className="chart-tooltip-row">
                  <span className="chart-tooltip-label">{s.label}</span>
                  <span
                    className="chart-tooltip-value"
                    style={{ color: s.color }}
                  >
                    {v != null ? f(v) : "---"}
                  </span>
                </div>
              );
            })}
          </div>
        )}
      </div>
    </div>
  );
}
