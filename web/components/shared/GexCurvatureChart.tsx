"use client";

/**
 * GexCurvatureChart — net gamma by strike as a curvature field.
 *
 * X = strike (ascending), Y = net GEX, area filled and split at zero
 * (teal above = stabilizing, magenta below = destabilizing). Spot and
 * GEX-flip are vertical rules; tagged strikes get triangle markers.
 *
 * Curvature is the discrete second derivative of net GEX with respect to
 * strike — where the gamma field bends, i.e. how fast dealer hedging
 * pressure changes per point of spot. Surfaced in the hover readout.
 */

import { useMemo, useState } from "react";
import type { GexBucket } from "@/lib/regime/useGex";
import { linearScale, pathFromPoints, type Point } from "@/lib/svgChart";

function fmtGex(v: number | null | undefined): string {
  if (v == null) return "---";
  const absVal = Math.abs(v);
  if (absVal >= 1_000_000)
    return `${v >= 0 ? "+" : ""}$${(v / 1_000_000).toFixed(1)}M`;
  if (absVal >= 1_000) return `${v >= 0 ? "+" : ""}$${(v / 1_000).toFixed(1)}K`;
  return `${v >= 0 ? "+" : ""}$${v.toFixed(0)}`;
}

/**
 * Discrete second derivative of net GEX w.r.t. strike, on a possibly
 * non-uniform strike grid:
 *
 *   f'' ≈ 2 · ( h₂·f₋₁ − (h₁+h₂)·f₀ + h₁·f₊₁ ) / ( h₁·h₂·(h₁+h₂) )
 *
 * Scaled by h̄² / max|f| so the output is dimensionless and comparable
 * across tickers (raw $/strike² is meaningless next to a $ level).
 * Endpoints have no centred stencil → null.
 *
 * Input MUST be sorted ascending by strike.
 */
export function curvatureField(buckets: GexBucket[]): (number | null)[] {
  const n = buckets.length;
  if (n < 3) return new Array(n).fill(null);

  const gaps: number[] = [];
  for (let i = 1; i < n; i++)
    gaps.push(buckets[i].strike - buckets[i - 1].strike);
  const sorted = [...gaps].sort((a, b) => a - b);
  const hBar = sorted[Math.floor(sorted.length / 2)] || 1;
  const maxAbs = Math.max(...buckets.map((b) => Math.abs(b.net_gex)), 1);
  const scale = (hBar * hBar) / maxAbs;

  const out: (number | null)[] = new Array(n).fill(null);
  for (let i = 1; i < n - 1; i++) {
    const h1 = buckets[i].strike - buckets[i - 1].strike;
    const h2 = buckets[i + 1].strike - buckets[i].strike;
    const denom = h1 * h2 * (h1 + h2);
    if (denom === 0) continue;
    const d2 =
      (2 *
        (h2 * buckets[i - 1].net_gex -
          (h1 + h2) * buckets[i].net_gex +
          h1 * buckets[i + 1].net_gex)) /
      denom;
    out[i] = d2 * scale;
  }
  return out;
}

export type GexCurvatureChartProps = {
  profile: GexBucket[];
  spot: number;
};

const W = 1000;
const H = 320;
const PAD = { top: 56, right: 20, bottom: 64, left: 72 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

const TAG_STYLE: Record<string, { color: string; up: boolean }> = {
  "MAX MAGNET": { color: "var(--signal-core)", up: true },
  "SECOND MAGNET": { color: "var(--signal-core)", up: true },
  "MAX ACCELERATOR": { color: "var(--fault)", up: true },
  "PUT WALL": { color: "var(--fault)", up: true },
  "CALL WALL": { color: "var(--signal-core)", up: true },
};

const TAG_LABEL: Record<string, string> = {
  "MAX MAGNET": "MAGNET",
  "SECOND MAGNET": "MAGNET 2",
  "MAX ACCELERATOR": "ACCEL",
  "PUT WALL": "PUT WALL",
  "CALL WALL": "CALL WALL",
};

export default function GexCurvatureChart({
  profile,
  spot,
}: GexCurvatureChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);

  const chart = useMemo(() => {
    // Drop the synthetic SPOT pseudo-row (net_gex 0) — it is a marker, not
    // a data point, and would dent the line and the curvature stencil.
    const buckets = profile
      .filter((b) => b.tag !== "SPOT")
      .sort((a, b) => a.strike - b.strike);
    if (buckets.length < 2) return null;

    const maxAbs = Math.max(...buckets.map((b) => Math.abs(b.net_gex)), 1);
    const x = linearScale(
      [buckets[0].strike, buckets[buckets.length - 1].strike],
      [PAD.left, PAD.left + PLOT_W],
    );
    const y = linearScale([-maxAbs, maxAbs], [PAD.top + PLOT_H, PAD.top]);
    const points: Point[] = buckets.map((b) => [x(b.strike), y(b.net_gex)]);
    const flipStrike =
      buckets.find((b) => b.tag === "GEX FLIP")?.strike ?? null;

    return {
      buckets,
      maxAbs,
      x,
      y,
      points,
      zeroY: y(0),
      curvature: curvatureField(buckets),
      flipStrike,
    };
  }, [profile]);

  if (!chart) {
    return (
      <div className="gex-profile-chart">
        <span className="gex-chart-title">GEX Profile</span>
        <div
          style={{
            padding: 24,
            textAlign: "center",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            color: "var(--text-muted)",
          }}
        >
          Not enough strikes to render the curvature field.
        </div>
      </div>
    );
  }

  const { buckets, maxAbs, x, y, points, zeroY, curvature, flipStrike } = chart;

  // Readout defaults to the strike nearest spot when the pointer is away.
  const spotIdx = buckets.reduce(
    (best, b, i) =>
      Math.abs(b.strike - spot) < Math.abs(buckets[best].strike - spot)
        ? i
        : best,
    0,
  );
  const readIdx = hoverIdx ?? spotIdx;
  const read = buckets[readIdx];

  const areaPath = `${pathFromPoints(points)} L${points[points.length - 1][0]},${zeroY} L${points[0][0]},${zeroY} Z`;
  const spotX = x(spot);

  function onMove(e: React.MouseEvent<SVGSVGElement>) {
    const rect = e.currentTarget.getBoundingClientRect();
    const px = ((e.clientX - rect.left) / rect.width) * W;
    if (px < PAD.left || px > PAD.left + PLOT_W) return setHoverIdx(null);
    let best = 0;
    for (let i = 1; i < points.length; i++) {
      if (Math.abs(points[i][0] - px) < Math.abs(points[best][0] - px))
        best = i;
    }
    setHoverIdx(best);
  }

  return (
    <div className="gex-profile-chart">
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          alignItems: "baseline",
        }}
      >
        <span className="gex-chart-title">
          GEX Profile &mdash; curvature field by strike
        </span>
        <span className="gex-chart-legend">
          <span style={{ color: "var(--signal-core)" }}>
            &#9632; Positive curvature (stabilizing)
          </span>{" "}
          <span style={{ color: "var(--fault)" }}>
            &#9632; Negative curvature (destabilizing)
          </span>
        </span>
      </div>

      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 11,
          color: "var(--text-muted)",
          letterSpacing: "0.08em",
          marginTop: 4,
          display: "flex",
          gap: 20,
        }}
      >
        <span>LAPLACE / CURVATURE FIELD</span>
        <span>
          STRIKE{" "}
          <span style={{ color: "var(--text-primary)" }}>
            {read.strike.toLocaleString()}
          </span>
        </span>
        <span>
          NET GEX{" "}
          <span
            style={{
              color: read.net_gex >= 0 ? "var(--signal-core)" : "var(--fault)",
            }}
          >
            {fmtGex(read.net_gex)}
          </span>
        </span>
        <span>
          CURVATURE{" "}
          <span style={{ color: "var(--text-primary)" }}>
            {curvature[readIdx] != null
              ? curvature[readIdx]!.toFixed(2)
              : "---"}
          </span>
        </span>
      </div>

      <svg
        viewBox={`0 0 ${W} ${H}`}
        width="100%"
        role="img"
        onMouseMove={onMove}
        onMouseLeave={() => setHoverIdx(null)}
        style={{ fontFamily: "var(--font-mono)", fontSize: 11, marginTop: 8 }}
      >
        <title>{`Net GEX by strike; spot ${spot.toLocaleString()}`}</title>

        {/* Split fill: clip the single area path to above/below the zero line */}
        <defs>
          <clipPath id="gex-above">
            <rect x={0} y={PAD.top} width={W} height={zeroY - PAD.top} />
          </clipPath>
          <clipPath id="gex-below">
            <rect x={0} y={zeroY} width={W} height={PAD.top + PLOT_H - zeroY} />
          </clipPath>
        </defs>
        <path
          d={areaPath}
          fill="var(--signal-core)"
          opacity={0.28}
          clipPath="url(#gex-above)"
        />
        <path
          d={areaPath}
          fill="var(--fault)"
          opacity={0.35}
          clipPath="url(#gex-below)"
        />

        {/* Axis: zero rule + symmetric extremes */}
        <line
          x1={PAD.left}
          y1={zeroY}
          x2={PAD.left + PLOT_W}
          y2={zeroY}
          stroke="var(--border-dim)"
        />
        <line
          x1={PAD.left}
          y1={PAD.top}
          x2={PAD.left}
          y2={PAD.top + PLOT_H}
          stroke="var(--border-dim)"
        />
        {[maxAbs, 0, -maxAbs].map((v) => (
          <text
            key={v}
            x={PAD.left - 8}
            y={y(v) + 4}
            textAnchor="end"
            fill="var(--text-muted)"
            fontSize={10}
          >
            {v === 0 ? "0" : fmtGex(v)}
          </text>
        ))}

        <path
          d={pathFromPoints(points)}
          fill="none"
          stroke="var(--signal-core)"
          strokeWidth={2}
          strokeLinejoin="round"
        />

        {/* Spot rule */}
        <line
          x1={spotX}
          y1={PAD.top}
          x2={spotX}
          y2={PAD.top + PLOT_H}
          stroke="var(--text-secondary)"
          strokeWidth={1.5}
        />
        <text
          x={spotX}
          y={PAD.top - 10}
          textAnchor="middle"
          fill="var(--text-primary)"
          fontSize={12}
        >
          SPOT {spot.toLocaleString()}
        </text>
        <circle
          cx={points[spotIdx][0]}
          cy={points[spotIdx][1]}
          r={5}
          fill="var(--signal-core)"
          stroke="var(--bg-panel)"
          strokeWidth={2}
        />

        {/* GEX flip rule */}
        {flipStrike != null && (
          <>
            <line
              x1={x(flipStrike)}
              y1={PAD.top}
              x2={x(flipStrike)}
              y2={PAD.top + PLOT_H}
              stroke="var(--warning)"
              strokeWidth={1.5}
              strokeDasharray="5 4"
            />
            {/* Own row above SPOT — the two rules sit close by construction */}
            <text
              x={
                x(flipStrike) +
                (x(flipStrike) > PAD.left + PLOT_W - 120 ? -8 : 8)
              }
              y={PAD.top - 28}
              textAnchor={
                x(flipStrike) > PAD.left + PLOT_W - 120 ? "end" : "start"
              }
              fill="var(--warning)"
              fontSize={12}
            >
              FLIP {flipStrike.toLocaleString()}
            </text>
          </>
        )}

        {/* Tagged strikes: triangle + label along the bottom.
            Labels alternate between two rows — adjacent tagged strikes
            (MAGNET / MAGNET 2) otherwise overlap. */}
        {(() => {
          let row = 0;
          return buckets.map((b, i) => {
            const style = b.tag ? TAG_STYLE[b.tag] : undefined;
            if (!style) return null;
            const cx = x(b.strike);
            const base = PAD.top + PLOT_H;
            const labelY = base + (row++ % 2 === 0 ? 30 : 44);
            return (
              <g key={`tag-${b.strike}-${i}`}>
                <polygon
                  points={`${cx},${base + 2} ${cx - 6},${base + 14} ${cx + 6},${base + 14}`}
                  fill={style.color}
                  opacity={0.85}
                />
                <text
                  x={cx}
                  y={labelY}
                  textAnchor="middle"
                  fill={style.color}
                  fontSize={10}
                  letterSpacing="0.08em"
                >
                  {TAG_LABEL[b.tag!] ?? b.tag}
                </text>
              </g>
            );
          });
        })()}

        {/* Hover crosshair */}
        {hoverIdx != null && (
          <line
            x1={points[hoverIdx][0]}
            y1={PAD.top}
            x2={points[hoverIdx][0]}
            y2={PAD.top + PLOT_H}
            stroke="var(--text-muted)"
            strokeWidth={1}
            strokeDasharray="2 3"
          />
        )}
      </svg>
    </div>
  );
}
