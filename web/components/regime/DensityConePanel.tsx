"use client";

import {
  useSpxDensity,
  type SpxDensityHorizon,
} from "@/lib/regime/useSpxDensity";
import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromBand,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

const WIDTH = 880;
const HEIGHT = 330;
const PAD = { top: 18, right: 66, bottom: 30, left: 52 };
// Sessions of realised context drawn to the left of the anchor. Kept short on
// purpose: the cone is the subject, and at 20 it was squeezed into ~20% of the
// width. 10 gives the forward fan ~35% while still showing where price came from.
const RECENT_N = 10;

const COLORS = {
  band: "var(--accent-vol, #7c6cf0)",
  median: "var(--text-muted)",
  realised: "var(--accent-warm, #F5A623)",
  baseline: "var(--text-secondary, #94a3b8)",
  grid: "rgba(148,163,184,0.08)",
  muted: "var(--text-muted)",
  warning: "var(--warning, #f59e0b)",
};

// (loKey, hiKey, fillOpacity) — outermost first so inner bands paint on top
const BANDS: Array<[keyof SpxDensityHorizon, keyof SpxDensityHorizon, number]> =
  [
    ["q05", "q95", 0.1],
    ["q10", "q90", 0.18],
    ["q25", "q75", 0.3],
  ];

const pct = (v: number) => `${(v * 100).toFixed(1)}%`;

export default function DensityConePanel() {
  const { data, loading, error } = useSpxDensity();
  const f = data?.forecast ?? null;

  if (loading && !data) {
    return (
      <div
        data-testid="spx-density-panel"
        style={{ color: "var(--text-muted)", fontSize: 12 }}
      >
        Loading density cone…
      </div>
    );
  }
  if (error || !f) {
    return (
      <div
        data-testid="spx-density-panel"
        style={{ color: "var(--text-muted)", fontSize: 12 }}
      >
        {error
          ? `Density cone unavailable: ${error}`
          : "No density forecast issued yet."}
      </div>
    );
  }

  const anchor = f.anchor_close;
  const rows = f.rows;
  const recent = (data?.recent_path ?? []).slice(-RECENT_N);
  const nRec = Math.max(recent.length, 2);

  // x in session units: realised path at -(n-1)..0 (0 = anchor), horizons at 1..5
  const xScale = linearScale([-(nRec - 1), 5.4], [PAD.left, WIDTH - PAD.right]);
  const values: number[] = [0];
  for (const r of rows) {
    values.push(r.q05, r.q95, r.baseline_q05, r.baseline_q95);
    if (r.realised_return != null) values.push(r.realised_return);
  }
  for (const p of recent) values.push(p.close / anchor - 1);
  const dom = finiteDomain(values);
  const lo = dom ? dom.lo * 1.08 : -0.05;
  const hi = dom ? dom.hi * 1.08 : 0.05;
  const yScale = linearScale([lo, hi], [HEIGHT - PAD.bottom, PAD.top]);

  const conePts = (key: keyof SpxDensityHorizon): Point[] => [
    [xScale(0), yScale(0)],
    ...rows.map((r, i) => [xScale(i + 1), yScale(r[key] as number)] as Point),
  ];
  const realisedPts: Point[] = recent.map((p, i) => [
    xScale(i - (recent.length - 1)),
    yScale(p.close / anchor - 1),
  ]);
  const yTicks = niceTicks(lo, hi, 5);

  return (
    <div className="section" data-testid="spx-density-panel">
      <div className="section-header">
        <div className="section-title">
          SPX 1–5D Density Cone
          <span
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: COLORS.muted,
              marginLeft: 8,
            }}
          >
            anchor {f.as_of} · {anchor.toFixed(2)} · GJR arm G/normal
            {f.origin === "reconstructed" ? " · RECONSTRUCTED" : ""}
          </span>
          {f.fallback_used && (
            <span
              style={{
                fontFamily: "var(--font-mono)",
                fontSize: 10,
                color: COLORS.warning,
                marginLeft: 8,
              }}
            >
              EWMA FALLBACK — GJR fit unavailable
            </span>
          )}
        </div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: COLORS.muted,
          }}
        >
          DISPLAY ONLY · NOT A TRADING SIGNAL
        </span>
      </div>
      <svg
        role="img"
        aria-label="SPX 1-5 trading-day conditional density cone, cumulative return"
        viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
        preserveAspectRatio="none"
        style={{ width: "100%", display: "block" }}
      >
        {yTicks.map((t) => (
          <g key={`y${t}`}>
            <line
              x1={PAD.left}
              x2={WIDTH - PAD.right}
              y1={yScale(t)}
              y2={yScale(t)}
              stroke={COLORS.grid}
            />
            <text
              x={PAD.left - 6}
              y={yScale(t) + 3}
              textAnchor="end"
              fontSize={10}
              fontFamily="var(--font-mono)"
              fill={COLORS.muted}
            >
              {pct(t)}
            </text>
          </g>
        ))}
        {[1, 2, 3, 4, 5].map((h) => (
          <text
            key={`x${h}`}
            x={xScale(h)}
            y={HEIGHT - PAD.bottom + 14}
            textAnchor="middle"
            fontSize={10}
            fontFamily="var(--font-mono)"
            fill={COLORS.muted}
          >
            H{h}
            {h === 4 ? "*" : ""}
          </text>
        ))}
        {BANDS.map(([blo, bhi, op]) => (
          <path
            key={`${blo}`}
            d={pathFromBand(conePts(bhi), conePts(blo))}
            fill={COLORS.band}
            fillOpacity={op}
          />
        ))}
        {/* EWMA baseline: thin outline only, never filled — a reference, not a forecast */}
        <path
          d={pathFromPoints(conePts("baseline_q10"))}
          fill="none"
          stroke={COLORS.baseline}
          strokeDasharray="6 4"
          opacity={0.6}
        />
        <path
          d={pathFromPoints(conePts("baseline_q90"))}
          fill="none"
          stroke={COLORS.baseline}
          strokeDasharray="6 4"
          opacity={0.6}
        />
        {/* p50: dotted, deliberately faint — NOT a direction call */}
        <path
          d={pathFromPoints(conePts("q50"))}
          fill="none"
          stroke={COLORS.median}
          strokeDasharray="2 4"
        />
        {realisedPts.length >= 2 && (
          <path
            d={pathFromPoints(realisedPts)}
            fill="none"
            stroke={COLORS.realised}
            strokeWidth={1.5}
          />
        )}
        <circle cx={xScale(0)} cy={yScale(0)} r={3} fill={COLORS.realised} />
      </svg>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: COLORS.muted,
          display: "flex",
          gap: 14,
          flexWrap: "wrap",
        }}
      >
        <span>80% band: {rows.map((r) => pct(r.band80_width)).join(" ")}</span>
        <span>
          vs EWMA ×: {rows.map((r) => r.width_ratio.toFixed(2)).join(" ")}
        </span>
        <span>
          p50 is not a direction call · H4* drawn but unscored by v13 · EWMA
          λ=0.94 outline
        </span>
      </div>
    </div>
  );
}
