"use client";

import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import type { GrgHistoryEntry } from "@/lib/regime/useGrgLive";

const WIDTH = 880;
const HEIGHT = 260;
const PAD = { top: 16, right: 28, bottom: 36, left: 28 };

// Match the radon palette: GRG amber, SPY teal, TLT pink.
const COLORS = {
  grg: "var(--accent-warm, #F5A623)",
  spy: "var(--accent-bg, #05AD98)",
  tlt: "var(--negative, #FB5E7B)",
  zero: "var(--border-dim)",
  grid: "rgba(148,163,184,0.08)",
};

function LegendSwatch({ color, label }: { color: string; label: string }) {
  return (
    <span
      style={{
        display: "inline-flex",
        alignItems: "center",
        gap: 6,
        fontFamily: "var(--font-mono)",
        fontSize: 10,
        letterSpacing: "0.06em",
        color: "var(--text-secondary)",
      }}
    >
      <svg width="12" height="12" aria-hidden="true">
        <circle cx="6" cy="6" r="4" fill={color} />
      </svg>
      {label}
    </span>
  );
}

function dateTickIndices(n: number, count = 5): number[] {
  if (n <= count) return Array.from({ length: n }, (_, i) => i);
  const step = (n - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round(i * step));
}

function shortDate(iso: string): string {
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso;
}

export default function GrgDivergenceChart({
  history,
}: {
  history: GrgHistoryEntry[];
}) {
  if (!history.length) {
    return (
      <div className="section" data-testid="grg-divergence-empty">
        <div className="section-header">
          <div className="section-title">90-Session Divergence Field</div>
        </div>
        <div
          className="section-body"
          style={{
            padding: 24,
            textAlign: "center",
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
            letterSpacing: "0.06em",
            textTransform: "uppercase",
          }}
        >
          No history available
        </div>
      </div>
    );
  }

  const xScale = linearScale(
    [0, Math.max(history.length - 1, 1)],
    [PAD.left, WIDTH - PAD.right],
  );

  // Shared z-axis. Anchor to ±3σ but widen if the data exceeds it.
  const zDomain = finiteDomain(
    history.flatMap((h) => [h.grg_z, h.spy_gamma_z, h.tlt_gamma_z]),
  );
  const hi = Math.max(
    3,
    zDomain ? Math.abs(zDomain.hi) : 3,
    zDomain ? Math.abs(zDomain.lo) : 3,
  );
  const yScale = linearScale([-hi, hi], [HEIGHT - PAD.bottom, PAD.top]);

  const seriesPath = (key: "grg_z" | "spy_gamma_z" | "tlt_gamma_z") =>
    pathFromNullablePoints(
      history.map((h, i): [number, number] | null => {
        const v = h[key];
        return v == null ? null : [xScale(i), yScale(v)];
      }),
    );

  const grgPath = seriesPath("grg_z");
  const spyPath = seriesPath("spy_gamma_z");
  const tltPath = seriesPath("tlt_gamma_z");
  const xTickIdx = dateTickIndices(history.length, 5);
  const sigmaTicks = [-3, 0, 3];

  return (
    <div className="section" data-testid="grg-divergence-chart">
      <div className="section-header">
        <div className="section-title">90-Session Divergence Field</div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <LegendSwatch color={COLORS.grg} label="GRG" />
          <LegendSwatch color={COLORS.spy} label="SPY" />
          <LegendSwatch color={COLORS.tlt} label="TLT" />
        </div>
      </div>
      <div className="section-body" style={{ padding: "8px 12px 12px" }}>
        <svg
          role="img"
          aria-label="90-session GRG divergence field"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: HEIGHT, display: "block" }}
        >
          <title>GRG, SPY gamma-z, TLT gamma-z over 90 sessions</title>

          {sigmaTicks.map((s) => {
            const y = yScale(s);
            return (
              <g key={`sig${s}`}>
                <line
                  x1={PAD.left}
                  x2={WIDTH - PAD.right}
                  y1={y}
                  y2={y}
                  stroke={s === 0 ? COLORS.zero : COLORS.grid}
                  strokeDasharray={s === 0 ? "2 3" : undefined}
                />
                <text
                  x={PAD.left}
                  y={y - 3}
                  fontSize={9}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-muted)"
                >
                  {s > 0 ? `+${s}σ` : `${s}σ`}
                </text>
              </g>
            );
          })}

          {xTickIdx.map((i) => {
            const x = xScale(i);
            const entry = history[i];
            if (!entry?.date) return null;
            return (
              <text
                key={`X${i}`}
                x={x}
                y={HEIGHT - PAD.bottom + 16}
                textAnchor="middle"
                fontSize={10}
                fontFamily="var(--font-mono)"
                fill="var(--text-secondary)"
              >
                {shortDate(entry.date)}
              </text>
            );
          })}

          <path
            d={tltPath}
            fill="none"
            stroke={COLORS.tlt}
            strokeWidth={1.2}
            strokeLinecap="round"
            opacity={0.85}
          />
          <path
            d={spyPath}
            fill="none"
            stroke={COLORS.spy}
            strokeWidth={1.2}
            strokeLinecap="round"
            opacity={0.85}
          />
          <path
            d={grgPath}
            fill="none"
            stroke={COLORS.grg}
            strokeWidth={1.8}
            strokeLinecap="round"
          />
        </svg>
      </div>
    </div>
  );
}
