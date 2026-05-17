"use client";

/**
 * GexProfileChart — divergent SVG bar chart of net gamma by strike.
 *
 * Extracted from web/components/GexPanel.tsx so the UW Analyze page can
 * render the same visualization. Both consumers import this single
 * source of truth.
 */

import { useMemo, useRef } from "react";
import type { GexBucket } from "@/lib/regime/useGex";

function fmtGex(v: number | null | undefined): string {
  if (v == null) return "---";
  const absVal = Math.abs(v);
  if (absVal >= 1_000_000)
    return `${v >= 0 ? "+" : ""}$${(v / 1_000_000).toFixed(1)}M`;
  if (absVal >= 1_000) return `${v >= 0 ? "+" : ""}$${(v / 1_000).toFixed(1)}K`;
  return `${v >= 0 ? "+" : ""}$${v.toFixed(0)}`;
}

function fmtPct(v: number | null | undefined): string {
  if (v == null) return "---";
  return `${v >= 0 ? "+" : ""}${v.toFixed(2)}%`;
}

export type GexProfileChartProps = {
  profile: GexBucket[];
  spot: number;
};

export default function GexProfileChart({
  profile,
  spot,
}: GexProfileChartProps) {
  const svgRef = useRef<SVGSVGElement>(null);
  const containerRef = useRef<HTMLDivElement>(null);

  const chartData = useMemo(() => {
    if (!profile.length) return { buckets: [], maxAbs: 1 };
    const maxAbs = Math.max(...profile.map((b) => Math.abs(b.net_gex)), 1);
    // Higher strikes at top (orderbook orientation). API returns ascending;
    // reverse here so presentation order matches reader intuition.
    const buckets = [...profile].sort((a, b) => b.strike - a.strike);
    return { buckets, maxAbs };
  }, [profile]);

  const barHeight = 22;
  const labelWidth = 110;
  const rightLabelWidth = 160;
  const chartWidth = 600;
  const barAreaWidth = chartWidth - labelWidth - rightLabelWidth;
  const midX = labelWidth + barAreaWidth / 2;
  const totalHeight = chartData.buckets.length * (barHeight + 4) + 8;

  return (
    <div
      ref={containerRef}
      className="gex-profile-chart"
      style={{ overflowX: "auto" }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          marginBottom: 8,
        }}
      >
        <span className="gex-chart-title">
          GEX Profile &mdash; Net gamma by strike
        </span>
        <span className="gex-chart-legend">
          <span style={{ color: "var(--signal-core)" }}>
            &#9632; Positive (stabilizing)
          </span>{" "}
          <span style={{ color: "var(--fault)" }}>
            &#9632; Negative (destabilizing)
          </span>
        </span>
      </div>
      <svg
        ref={svgRef}
        viewBox={`0 0 ${chartWidth} ${totalHeight}`}
        width="100%"
        height={totalHeight}
        style={{ fontFamily: "var(--font-mono)", fontSize: 11 }}
      >
        <line
          x1={midX}
          y1={0}
          x2={midX}
          y2={totalHeight}
          stroke="var(--border-dim)"
          strokeWidth={1}
        />

        {chartData.buckets.map((bucket, i) => {
          const y = i * (barHeight + 4) + 4;
          const barWidthPx =
            (Math.abs(bucket.net_gex) / chartData.maxAbs) * (barAreaWidth / 2);
          const isPositive = bucket.net_gex >= 0;
          const barX = isPositive ? midX : midX - barWidthPx;
          const barColor = isPositive ? "var(--signal-core)" : "var(--fault)";

          const isSpot = bucket.tag === "SPOT";
          const tagColor =
            bucket.tag === "GEX FLIP"
              ? "var(--warning)"
              : bucket.tag === "SPOT"
                ? "var(--signal-strong)"
                : bucket.tag?.includes("MAGNET")
                  ? "var(--signal-core)"
                  : bucket.tag?.includes("ACCEL")
                    ? "var(--fault)"
                    : "var(--text-secondary)";

          return (
            <g key={`${bucket.strike}-${i}`}>
              <text
                x={labelWidth - 8}
                y={y + barHeight / 2 + 4}
                textAnchor="end"
                fill={isSpot ? "var(--signal-strong)" : "var(--text-secondary)"}
                fontWeight={isSpot ? 700 : 400}
              >
                {bucket.strike.toLocaleString()}
              </text>
              <text
                x={4}
                y={y + barHeight / 2 + 4}
                textAnchor="start"
                fill="var(--text-muted)"
                fontSize={9}
              >
                {fmtPct(bucket.pct_from_spot)}
              </text>
              <rect
                x={barX}
                y={y}
                width={Math.max(barWidthPx, 1)}
                height={barHeight}
                fill={barColor}
                rx={2}
                opacity={0.85}
              />
              <text
                x={chartWidth - rightLabelWidth + 8}
                y={y + barHeight / 2 + 4}
                textAnchor="start"
                fill={isPositive ? "var(--signal-core)" : "var(--fault)"}
                fontSize={10}
              >
                {fmtGex(bucket.net_gex)}
              </text>
              {bucket.tag && (
                <text
                  x={chartWidth - 8}
                  y={y + barHeight / 2 + 4}
                  textAnchor="end"
                  fill={tagColor}
                  fontWeight={700}
                  fontSize={10}
                >
                  {bucket.tag === "MAX MAGNET"
                    ? "MAX MAGNET \u25B2"
                    : bucket.tag === "MAX ACCELERATOR"
                      ? "MAX ACCEL \u25BC"
                      : bucket.tag === "GEX FLIP"
                        ? "GEX FLIP \u25C4"
                        : bucket.tag === "SPOT"
                          ? "\u25C4 SPOT"
                          : bucket.tag}
                </text>
              )}
              {isSpot && (
                <line
                  x1={labelWidth}
                  y1={y + barHeight + 2}
                  x2={chartWidth - rightLabelWidth}
                  y2={y + barHeight + 2}
                  stroke="var(--signal-strong)"
                  strokeWidth={1}
                  strokeDasharray="4 2"
                  opacity={0.5}
                />
              )}
            </g>
          );
        })}
      </svg>
    </div>
  );
}

// Helper to convert UW analyze gex_by_strike rows into GexBucket shape.
// UW analyze rows: { strike, net_gamma, distance_pct (fraction), is_call_wall, is_put_wall }
// GexBucket:      { strike, call_gex, put_gex, net_gex, pct_from_spot, tag }
export function uwGexRowsToBuckets(
  rows:
    | Array<{
        strike: number;
        net_gamma: number | null;
        call_gamma?: number | null;
        put_gamma?: number | null;
        distance_pct?: number | null;
        is_call_wall?: boolean;
        is_put_wall?: boolean;
      }>
    | null
    | undefined,
  spot: number | null,
  gexFlipStrike: number | null,
): GexBucket[] {
  if (!rows || rows.length === 0) return [];
  const sorted = [...rows].sort((a, b) => b.strike - a.strike);
  let spotInserted = false;
  const out: GexBucket[] = [];

  for (let i = 0; i < sorted.length; i++) {
    const r = sorted[i];
    const next = sorted[i + 1];
    let tag: string | null = null;
    if (r.is_call_wall) tag = "CALL WALL";
    else if (r.is_put_wall) tag = "PUT WALL";
    else if (gexFlipStrike != null && r.strike === gexFlipStrike)
      tag = "GEX FLIP";

    out.push({
      strike: r.strike,
      call_gex: r.call_gamma ?? 0,
      put_gex: r.put_gamma ?? 0,
      net_gex: r.net_gamma ?? 0,
      pct_from_spot: (r.distance_pct ?? 0) * 100,
      tag,
    });

    // Insert SPOT pseudo-row at the right position once we cross it.
    if (
      !spotInserted &&
      spot != null &&
      next != null &&
      r.strike >= spot &&
      next.strike < spot
    ) {
      out.push({
        strike: spot,
        call_gex: 0,
        put_gex: 0,
        net_gex: 0,
        pct_from_spot: 0,
        tag: "SPOT",
      });
      spotInserted = true;
    }
  }
  return out;
}
