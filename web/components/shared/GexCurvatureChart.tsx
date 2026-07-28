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

import { useId, useMemo, useState } from "react";
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
  /**
   * GEX-flip level for the dashed rule. Optional because the regime feed tags
   * a real bucket `GEX FLIP`, but the flip is an interpolated zero-crossing —
   * on the stock path it routinely falls BETWEEN listed strikes, so an
   * exact-strike tag match would silently drop the rule. An explicit value
   * wins over the tag when both are present.
   */
  flipStrike?: number | null;
};

const W = 1000;
const H = 320;
const PAD = { top: 56, right: 20, bottom: 64, left: 72 };
const PLOT_W = W - PAD.left - PAD.right;
const PLOT_H = H - PAD.top - PAD.bottom;

/** Marker colour + short label per tagged strike. One map, not two parallel
 *  ones — a new tag can't be added to the colours and forgotten in the labels. */
const TAG_MARKER: Record<string, { color: string; label: string }> = {
  "MAX MAGNET": { color: "var(--signal-core)", label: "MAGNET" },
  "SECOND MAGNET": { color: "var(--signal-core)", label: "MAGNET 2" },
  "MAX ACCELERATOR": { color: "var(--fault)", label: "ACCEL" },
  "PUT WALL": { color: "var(--fault)", label: "PUT WALL" },
  "CALL WALL": { color: "var(--signal-core)", label: "CALL WALL" },
};

export default function GexCurvatureChart({
  profile,
  spot,
  flipStrike: flipStrikeProp,
}: GexCurvatureChartProps) {
  const [hoverIdx, setHoverIdx] = useState<number | null>(null);
  // SVG ids are document-global: two charts on one page would otherwise
  // share (and fight over) the same clip paths.
  const uid = useId();

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
      flipStrikeProp ??
      buckets.find((b) => b.tag === "GEX FLIP")?.strike ??
      null;

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
  }, [profile, flipStrikeProp]);

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
  // hoverIdx is state and the profile is re-polled underneath it (regime GEX
  // every 60s, the live-spot splice more often, and the stock window resizes
  // as spot moves). A shrunk bucket list would leave the index dangling and
  // points[hoverIdx][0] would throw — clamp on read, don't trust the state.
  const safeHoverIdx =
    hoverIdx != null && hoverIdx < buckets.length ? hoverIdx : null;
  const readIdx = safeHoverIdx ?? spotIdx;
  const read = buckets[readIdx];

  const areaPath = `${pathFromPoints(points)} L${points[points.length - 1][0]},${zeroY} L${points[0][0]},${zeroY} Z`;
  // Spot/flip can sit outside the rendered strike span (the regime feed
  // splices a live spot independent of the profile's strike grid). linearScale
  // extrapolates, so clamp to the plot: the rule parks on the edge it exceeded
  // rather than being drawn outside the axes. The label still states the value.
  const clampX = (v: number) =>
    Math.min(PAD.left + PLOT_W, Math.max(PAD.left, x(v)));
  const spotX = clampX(spot);

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
        {/* The fill is keyed on the sign of NET GEX, not on curvature —
            labelling it "curvature" would misstate what the colour means
            to a trader. Curvature is the separate readout below. */}
        {/* Hue rides the swatch only; the words wear a text token. The
            teal/magenta pair separates by just ΔE 7.3 under deuteranopia, so
            colour is never the sole channel here — the zero rule splits the
            fill by position and the readout carries a signed value. */}
        <span
          className="gex-chart-legend"
          style={{ color: "var(--text-secondary)" }}
        >
          <span style={{ color: "var(--signal-core)" }}>&#9632;</span> Positive
          GEX (stabilizing){" "}
          <span style={{ color: "var(--fault)" }}>&#9632;</span> Negative GEX
          (destabilizing)
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
            {curvature[readIdx]?.toFixed(2) ?? "---"}
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
          <clipPath id={`gex-above-${uid}`}>
            <rect x={0} y={PAD.top} width={W} height={zeroY - PAD.top} />
          </clipPath>
          <clipPath id={`gex-below-${uid}`}>
            <rect x={0} y={zeroY} width={W} height={PAD.top + PLOT_H - zeroY} />
          </clipPath>
        </defs>
        <path
          d={areaPath}
          fill="var(--signal-core)"
          opacity={0.28}
          clipPath={`url(#gex-above-${uid})`}
        />
        <path
          d={areaPath}
          fill="var(--fault)"
          opacity={0.35}
          clipPath={`url(#gex-below-${uid})`}
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
              x1={clampX(flipStrike)}
              y1={PAD.top}
              x2={clampX(flipStrike)}
              y2={PAD.top + PLOT_H}
              stroke="var(--warning)"
              strokeWidth={1.5}
              strokeDasharray="5 4"
            />
            {/* Own row above SPOT — the two rules sit close by construction */}
            <text
              x={
                clampX(flipStrike) +
                (clampX(flipStrike) > PAD.left + PLOT_W - 120 ? -8 : 8)
              }
              y={PAD.top - 28}
              textAnchor={
                clampX(flipStrike) > PAD.left + PLOT_W - 120 ? "end" : "start"
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
            const marker = b.tag ? TAG_MARKER[b.tag] : undefined;
            if (!marker) return null;
            const cx = x(b.strike);
            const base = PAD.top + PLOT_H;
            const labelY = base + (row++ % 2 === 0 ? 30 : 44);
            return (
              <g key={`tag-${b.strike}-${i}`}>
                <polygon
                  points={`${cx},${base + 2} ${cx - 6},${base + 14} ${cx + 6},${base + 14}`}
                  fill={marker.color}
                  opacity={0.85}
                />
                <text
                  x={cx}
                  y={labelY}
                  textAnchor="middle"
                  fill={marker.color}
                  fontSize={10}
                  letterSpacing="0.08em"
                >
                  {marker.label}
                </text>
              </g>
            );
          });
        })()}

        {/* Hover crosshair */}
        {safeHoverIdx != null && (
          <line
            x1={points[safeHoverIdx][0]}
            y1={PAD.top}
            x2={points[safeHoverIdx][0]}
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
