"use client";

import { linearScale, niceTicks } from "@/lib/svgChart";
import type {
  TopNetImpactData,
  TopNetImpactRow,
} from "@/lib/regime/useTopNetImpact";

const COLORS = {
  pos: "var(--positive, #22c55e)",
  neg: "var(--negative, #ef4444)",
  grid: "rgba(148,163,184,0.10)",
  zero: "var(--border-dim)",
  muted: "var(--text-muted)",
};

const WIDTH = 520;
const PAD = { top: 14, right: 24, bottom: 34, left: 104 };
const ROW_H = 16;

function fmtM(v: number): string {
  const m = v / 1_000_000;
  if (Math.abs(m) >= 1000) return `${(m / 1000).toFixed(1)}B`;
  return `${m.toFixed(0)}M`;
}

/** rank_change = prev_rank - rank → positive = climbed toward rank 1. */
function rankBadge(r: TopNetImpactRow): { glyph: string; color: string } {
  if (r.prev_rank == null) return { glyph: "•", color: COLORS.muted };
  const rc = r.rank_change ?? 0;
  if (rc > 0) return { glyph: `▲${rc}`, color: COLORS.pos };
  if (rc < 0) return { glyph: `▼${-rc}`, color: COLORS.neg };
  return { glyph: "—", color: COLORS.muted };
}

export function TopNetImpactChart({ data }: { data: TopNetImpactData | null }) {
  const rows = data?.rows ?? [];

  if (!rows.length) {
    return (
      <div className="section" data-testid="top-net-impact-empty">
        <div className="section-header">
          <div className="section-title">Top Net Impact</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          No top-net-impact snapshot available.
        </div>
      </div>
    );
  }

  const height = PAD.top + rows.length * ROW_H + PAD.bottom;
  const maxAbs =
    Math.max(...rows.map((r) => Math.abs(r.net_premium ?? 0)), 1) || 1;
  const xScale = linearScale([-maxAbs, maxAbs], [PAD.left, WIDTH - PAD.right]);
  const x0 = xScale(0);
  const xTicks = niceTicks(-maxAbs, maxAbs, 5);

  return (
    <div
      className="section"
      data-testid="top-net-impact-chart"
      style={{ height: "100%", display: "flex", flexDirection: "column" }}
    >
      <div className="section-header">
        <div className="section-title">
          Top Net Impact Chart{data?.data_date ? ` — ${data.data_date}` : ""}
        </div>
        <div
          style={{
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.06em",
            color: "var(--text-muted)",
          }}
        >
          ▲▼ RANK Δ / UPDATE
        </div>
      </div>
      <div
        className="section-body"
        style={{
          padding: "8px 8px 4px",
          flex: 1,
          minHeight: 0,
          display: "flex",
        }}
      >
        <svg
          role="img"
          aria-label="Top tickers by net option premium, bullish and bearish, with per-update rank change"
          viewBox={`0 0 ${WIDTH} ${height}`}
          preserveAspectRatio="none"
          style={{ width: "100%", flex: 1, minHeight: 0, display: "block" }}
        >
          <title>Top net impact — net option premium by ticker</title>

          {/* Vertical grid + bottom axis. */}
          {xTicks.map((v) => {
            const x = xScale(v);
            return (
              <g key={`gx${v}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={PAD.top}
                  y2={height - PAD.bottom}
                  stroke={v === 0 ? COLORS.zero : COLORS.grid}
                  strokeDasharray={v === 0 ? undefined : "2 3"}
                />
                <text
                  x={x}
                  y={height - PAD.bottom + 16}
                  textAnchor="middle"
                  fontSize={11}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-muted)"
                >
                  {v === 0 ? "0" : fmtM(v)}
                </text>
              </g>
            );
          })}
          <text
            x={(PAD.left + WIDTH - PAD.right) / 2}
            y={height - 2}
            textAnchor="middle"
            fontSize={12}
            fontFamily="var(--font-mono)"
            fill="var(--text-secondary)"
            letterSpacing="0.06em"
          >
            NET PREMIUMS
          </text>

          {/* One diverging bar per ticker, with rank-Δ badge + ticker in the
              left gutter. */}
          {rows.map((r, i) => {
            const v = r.net_premium ?? 0;
            const yTop = PAD.top + i * ROW_H;
            const yMid = yTop + ROW_H / 2;
            const xv = xScale(v);
            const barX = Math.min(x0, xv);
            const barW = Math.max(1, Math.abs(xv - x0));
            const positive = v >= 0;
            const badge = rankBadge(r);
            return (
              <g key={r.ticker}>
                <rect
                  x={barX}
                  y={yTop + 2}
                  width={barW}
                  height={ROW_H - 4}
                  rx={2}
                  fill={positive ? COLORS.pos : COLORS.neg}
                  fillOpacity={0.85}
                >
                  <title>{`${r.ticker}: ${fmtM(v)} net premium`}</title>
                </rect>
                {/* rank-Δ badge, far left */}
                <text
                  x={6}
                  y={yMid + 3.5}
                  textAnchor="start"
                  fontSize={11}
                  fontFamily="var(--font-mono)"
                  fill={badge.color}
                >
                  {badge.glyph}
                </text>
                {/* ticker, right-aligned against the bars */}
                <text
                  x={PAD.left - 8}
                  y={yMid + 3.5}
                  textAnchor="end"
                  fontSize={12.5}
                  fontFamily="var(--font-mono)"
                  fill={positive ? COLORS.pos : COLORS.neg}
                >
                  {r.ticker}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
    </div>
  );
}
