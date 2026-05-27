"use client";

import { useEffect, useMemo, useRef, useState } from "react";

import type { components } from "@/lib/types";
import { finiteDomain, linearScale, pathFromPoints } from "@/lib/svgChart";

type CanaryHistoryRow = components["schemas"]["CanaryHistoryRow"];

const MARGIN = { top: 16, right: 64, bottom: 28, left: 40 };
const HEIGHT = 280;
const SPX_COLOR = "var(--text-primary)";

// y-domain pinned to the composite range so axis labels stay legible even when
// a window of mostly-NONE days has a tiny actual span.
const Y_DOMAIN: [number, number] = [0, 100];

// Band thresholds mirror src/uw_scan/cards/canary_scoring.py compute_band().
// Hard-coded to keep the chart self-contained — if the thresholds ever change
// they'd need to be regenerated; chart still renders correctly with stale
// reference lines because the `band` field on each row drives the dot color.
const WATCH_THRESHOLD = 25;
const BUY_THRESHOLD = 50;
const STRONG_BUY_THRESHOLD = 75;

const BAND_COLOR: Record<CanaryHistoryRow["band"], string> = {
  NONE: "var(--text-muted)",
  WATCH: "var(--warning)",
  BUY: "var(--positive)",
  STRONG_BUY: "var(--accent-vivid)",
};

function fmtDateLabel(d: Date): string {
  const m = d.toLocaleString("en-US", { month: "short" });
  return `${m} ${d.getFullYear().toString().slice(2)}`;
}

export function CanaryScoreChart({
  history,
  title,
}: {
  history: CanaryHistoryRow[];
  title: string;
}) {
  const containerRef = useRef<HTMLDivElement>(null);
  const svgRef = useRef<SVGSVGElement>(null);
  const [width, setWidth] = useState(800);
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  const [hoverPos, setHoverPos] = useState<{ x: number; y: number } | null>(
    null,
  );

  // History arrives newest-first (DB ORDER BY data_date DESC) — flip to draw
  // left→right in time order.
  const ordered = useMemo(
    () =>
      [...history].sort((a, b) =>
        a.data_date < b.data_date ? -1 : a.data_date > b.data_date ? 1 : 0,
      ),
    [history],
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

  const innerW = Math.max(0, width - MARGIN.left - MARGIN.right);
  const innerH = HEIGHT - MARGIN.top - MARGIN.bottom;

  if (ordered.length < 2) {
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
              data-testid="canary-score-chart-empty"
            >
              NO HISTORY AVAILABLE
            </div>
          </div>
        </div>
      </div>
    );
  }

  const x = linearScale([0, ordered.length - 1], [0, innerW]);
  const y = linearScale(Y_DOMAIN, [innerH, 0]);

  const points: [number, number][] = ordered.map((d, i) => [x(i), y(d.score)]);
  const path = pathFromPoints(points);

  const yTicks = [0, 25, 50, 75, 100];

  // SPX overlay — right axis. Domain padded ~5% so the line doesn't kiss the
  // frame; ticks are 5 evenly spaced values within the padded domain.
  const spxDomain = finiteDomain(ordered.map((d) => d.spx_close ?? null));
  const yRight = (() => {
    if (!spxDomain) return null;
    const pad = (spxDomain.hi - spxDomain.lo) * 0.05 || 1;
    return linearScale([spxDomain.lo - pad, spxDomain.hi + pad], [innerH, 0]);
  })();
  const spxPath = (() => {
    if (!yRight) return "";
    const pts = ordered
      .map((d, i): [number, number] | null =>
        d.spx_close == null ? null : [x(i), yRight(d.spx_close)],
      )
      .filter((p): p is [number, number] => p != null);
    return pathFromPoints(pts);
  })();
  const rightTicks = (() => {
    if (!yRight || !spxDomain) return [] as number[];
    const pad = (spxDomain.hi - spxDomain.lo) * 0.05 || 1;
    const lo = spxDomain.lo - pad;
    const hi = spxDomain.hi + pad;
    const step = (hi - lo) / 4;
    return [0, 1, 2, 3, 4].map((k) => lo + step * k);
  })();

  // X ticks: 5–7 evenly spaced — labeled "Mon YY"
  const xTickCount = Math.max(2, Math.min(7, Math.floor(innerW / 90)));
  const xTickIdx = Array.from({ length: xTickCount }, (_, k) =>
    Math.round(((ordered.length - 1) * k) / (xTickCount - 1)),
  );
  const dates = ordered.map((d) => new Date(d.data_date));

  function onMove(e: React.MouseEvent<SVGRectElement>) {
    const rect = svgRef.current?.getBoundingClientRect();
    if (!rect) return;
    const localX = e.clientX - rect.left - MARGIN.left;
    const frac = innerW > 0 ? localX / innerW : 0;
    let i = Math.round(frac * (ordered.length - 1));
    i = Math.max(0, Math.min(ordered.length - 1, i));
    setHoverIdx(i);
    setHoverPos({ x: e.clientX - rect.left, y: e.clientY - rect.top });
  }

  function onLeave() {
    setHoverIdx(null);
    setHoverPos(null);
  }

  const hoverEntry = hoverIdx != null ? ordered[hoverIdx] : null;
  const tooltipSide =
    hoverPos && hoverPos.x > width / 2
      ? { right: width - hoverPos.x + 12 }
      : { left: (hoverPos?.x ?? 0) + 12 };

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
        <div
          style={{
            display: "flex",
            gap: 12,
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: "var(--text-muted)",
            textTransform: "uppercase",
            letterSpacing: "0.1em",
          }}
        >
          <LegendSwatch label="None" color={BAND_COLOR.NONE} />
          <LegendSwatch label="Watch" color={BAND_COLOR.WATCH} />
          <LegendSwatch label="Buy" color={BAND_COLOR.BUY} />
          <LegendSwatch label="Strong" color={BAND_COLOR.STRONG_BUY} />
          {yRight && <LegendLine label="SPX" color={SPX_COLOR} />}
        </div>
      </div>

      <div ref={containerRef} className="cri-history-chart-shell">
        <div className="chart-surface cri-history-chart-surface">
          <svg
            ref={svgRef}
            className="cri-history-chart-svg"
            viewBox={`0 0 ${width} ${HEIGHT}`}
            role="img"
            aria-label={`${title} — composite score over ${ordered.length} sessions`}
            data-testid="canary-score-chart"
          >
            <g transform={`translate(${MARGIN.left},${MARGIN.top})`}>
              {/* y gridlines + labels */}
              {yTicks.map((v) => (
                <g key={`yt-${v}`}>
                  <line
                    x1={0}
                    x2={innerW}
                    y1={y(v)}
                    y2={y(v)}
                    stroke="var(--chart-grid)"
                    strokeWidth={1}
                  />
                  <text
                    x={-8}
                    y={y(v)}
                    textAnchor="end"
                    dominantBaseline="middle"
                    fontSize={10}
                    fontFamily="var(--font-mono)"
                    fill="var(--text-muted)"
                  >
                    {v}
                  </text>
                </g>
              ))}

              {/* Band-threshold reference lines */}
              {[WATCH_THRESHOLD, BUY_THRESHOLD, STRONG_BUY_THRESHOLD].map(
                (v) => (
                  <line
                    key={`band-${v}`}
                    x1={0}
                    x2={innerW}
                    y1={y(v)}
                    y2={y(v)}
                    stroke="var(--border-dim)"
                    strokeWidth={1}
                    strokeDasharray="2 3"
                  />
                ),
              )}

              {/* SPX overlay (right axis) — drawn under the score so the
                  band-colored dots remain readable. */}
              {yRight && (
                <path
                  d={spxPath}
                  fill="none"
                  stroke={SPX_COLOR}
                  strokeWidth={1.2}
                  opacity={0.6}
                />
              )}

              {/* Right axis ticks (SPX) */}
              {yRight &&
                rightTicks.map((v, i) => (
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
                    fill={SPX_COLOR}
                  >
                    {Math.round(v).toLocaleString()}
                  </text>
                ))}

              {/* Score line */}
              <path
                d={path}
                fill="none"
                stroke="var(--accent-bg)"
                strokeWidth={1.5}
              />

              {/* Dots colored by band */}
              {ordered.map((d, i) => (
                <circle
                  key={d.data_date}
                  cx={x(i)}
                  cy={y(d.score)}
                  r={1.5}
                  fill={BAND_COLOR[d.band]}
                />
              ))}

              {/* x baseline */}
              <line
                x1={0}
                x2={innerW}
                y1={innerH}
                y2={innerH}
                stroke="var(--chart-axis)"
              />

              {/* x tick labels */}
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

              {/* Capture overlay */}
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
            style={{ ...tooltipSide, top: hoverPos.y - 10 }}
          >
            <div className="chart-tooltip-date">{hoverEntry.data_date}</div>
            <div className="chart-tooltip-row">
              <span className="chart-tooltip-label">Score</span>
              <span className="chart-tooltip-value">
                {hoverEntry.score.toFixed(2)}
              </span>
            </div>
            <div className="chart-tooltip-row">
              <span className="chart-tooltip-label">Band</span>
              <span
                className="chart-tooltip-value"
                style={{ color: BAND_COLOR[hoverEntry.band] }}
              >
                {hoverEntry.band}
              </span>
            </div>
            <div className="chart-tooltip-row">
              <span className="chart-tooltip-label">State</span>
              <span className="chart-tooltip-value">
                {hoverEntry.warning_state === "NONE"
                  ? "—"
                  : hoverEntry.warning_state.replace(/_/g, " ")}
              </span>
            </div>
            {hoverEntry.spx_close != null && (
              <div className="chart-tooltip-row">
                <span className="chart-tooltip-label">SPX</span>
                <span
                  className="chart-tooltip-value"
                  style={{ color: SPX_COLOR }}
                >
                  {hoverEntry.spx_close.toLocaleString(undefined, {
                    maximumFractionDigits: 2,
                  })}
                </span>
              </div>
            )}
          </div>
        )}
      </div>
    </div>
  );
}

function LegendSwatch({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span
        style={{
          width: 8,
          height: 8,
          background: color,
          borderRadius: "50%",
          display: "inline-block",
        }}
      />
      {label}
    </span>
  );
}

function LegendLine({ label, color }: { label: string; color: string }) {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 4 }}>
      <span
        style={{
          width: 12,
          height: 2,
          background: color,
          display: "inline-block",
          opacity: 0.6,
        }}
      />
      {label}
    </span>
  );
}
