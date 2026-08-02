"use client";

import {
  useSpxDensityIssued,
  type SpxDensityForecast,
} from "@/lib/regime/useSpxDensity";
import {
  linearScale,
  pathFromBand,
  pathFromPoints,
  type Point,
} from "@/lib/svgChart";

const W = 160;
const H = 110;
const PAD = { top: 8, right: 8, bottom: 16, left: 8 };

const COLORS = {
  band: "var(--positive, #05ad98)",
  realised: "var(--accent-warm, #F5A623)",
  muted: "var(--text-muted)",
  good: "var(--positive, #22c55e)",
  bad: "var(--negative, #ef4444)",
};

function MiniCone({ f }: { f: SpxDensityForecast }) {
  const rows = f.rows;
  const xScale = linearScale([0, 5], [PAD.left, W - PAD.right]);
  const vals: number[] = [0];
  for (const r of rows) {
    vals.push(r.q05, r.q95);
    if (r.realised_return != null) vals.push(r.realised_return);
  }
  const lo = Math.min(...vals) * 1.1;
  const hi = Math.max(...vals) * 1.1;
  const yScale = linearScale([lo, hi], [H - PAD.bottom, PAD.top]);

  const edge = (
    key: "q05" | "q10" | "q25" | "q75" | "q90" | "q95",
  ): Point[] => [
    [xScale(0), yScale(0)],
    ...rows.map((r, i) => [xScale(i + 1), yScale(r[key])] as Point),
  ];
  const realised: Point[] = [[xScale(0), yScale(0)]];
  for (const r of rows) {
    if (r.realised_return != null)
      realised.push([xScale(r.h), yScale(r.realised_return)]);
  }

  const settled = rows.filter(
    (r) => r.inside_band80 != null && r.scored_horizon,
  );
  const misses = settled.filter((r) => r.inside_band80 === false);
  const badge =
    settled.length === 0
      ? "PENDING"
      : misses.length === 0
        ? `IN ${settled.length}/${settled.length} ✓`
        : `OUT@H${misses[0].h} ✗`;
  const badgeColor =
    settled.length === 0
      ? COLORS.muted
      : misses.length === 0
        ? COLORS.good
        : COLORS.bad;

  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        padding: 6,
      }}
    >
      <div
        style={{
          display: "flex",
          justifyContent: "space-between",
          fontFamily: "var(--font-mono)",
          fontSize: 9,
          color: COLORS.muted,
        }}
      >
        <span>
          {f.as_of}
          {f.origin === "reconstructed" ? " · RECON" : ""}
          {f.fallback_used ? " · EWMA FB" : ""}
        </span>
        <span style={{ color: badgeColor }}>{badge}</span>
      </div>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        preserveAspectRatio="none"
        style={{ width: "100%", display: "block" }}
      >
        <path
          d={pathFromBand(edge("q05"), edge("q95"))}
          fill={COLORS.band}
          fillOpacity={0.12}
        />
        <path
          d={pathFromBand(edge("q10"), edge("q90"))}
          fill={COLORS.band}
          fillOpacity={0.2}
        />
        <path
          d={pathFromBand(edge("q25"), edge("q75"))}
          fill={COLORS.band}
          fillOpacity={0.32}
        />
        {realised.length >= 2 && (
          <path
            d={pathFromPoints(realised)}
            fill="none"
            stroke={COLORS.realised}
            strokeWidth={1.2}
          />
        )}
        {realised.slice(1).map(([x, y], i) => (
          <circle key={i} cx={x} cy={y} r={2} fill={COLORS.realised} />
        ))}
      </svg>
    </div>
  );
}

export default function DensityConeStrip() {
  const { data } = useSpxDensityIssued();
  const forecasts = data?.forecasts ?? [];
  if (forecasts.length === 0) return null;

  const rates = data?.hit_rates ?? [];
  const fmt = (o: string) => {
    const r = rates.find((x) => x.origin === o);
    return r ? `${r.inside}/${r.total}` : "0/0";
  };

  // Same `.section` chrome as the GEX panel and the cone above it — the strip used to
  // sit bare on the page background, which read as chart debris rather than a panel.
  return (
    <div className="section" data-testid="spx-density-strip">
      <div className="section-header">
        <div className="section-title">Recent Cones vs Realised</div>
        <span
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 10,
            color: COLORS.muted,
          }}
        >
          80%-band hit rate (scored horizons) · prospective {fmt("prospective")}{" "}
          · reconstructed {fmt("reconstructed")} (in-sample)
        </span>
      </div>
      <div
        className="section-body"
        style={{
          padding: 16,
          display: "grid",
          gridTemplateColumns: "repeat(auto-fit, minmax(150px, 1fr))",
          gap: 10,
        }}
      >
        {forecasts.map((f) => (
          <MiniCone key={f.as_of} f={f} />
        ))}
      </div>
    </div>
  );
}
