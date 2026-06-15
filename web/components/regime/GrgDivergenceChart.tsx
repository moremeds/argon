"use client";

import {
  finiteDomain,
  linearScale,
  pathFromNullablePoints,
} from "@/lib/svgChart";
import type { GrgEvent, GrgHistoryEntry } from "@/lib/regime/useGrgLive";

// Wider, responsive aspect — the left card column is narrow so the chart gets
// the room. height:auto keeps circles round (no preserveAspectRatio="none").
const WIDTH = 1120;
const HEIGHT = 300;
const PAD = { top: 18, right: 48, bottom: 36, left: 30 };

// Match the radon palette: GRG amber, SPY teal, TLT pink. SPY price is a soft
// white so it reads as context behind the σ signal lines.
const COLORS = {
  grg: "var(--accent-warm, #F5A623)",
  spy: "var(--accent-bg, #05AD98)",
  tlt: "var(--negative, #FB5E7B)",
  price: "rgba(226,232,240,0.8)",
  top: "var(--positive, #2BD9A8)",
  bottom: "var(--negative, #FB5E7B)",
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

function dateTickIndices(n: number, count = 6): number[] {
  if (n <= count) return Array.from({ length: n }, (_, i) => i);
  const step = (n - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round(i * step));
}

function shortDate(iso: string): string {
  const parts = iso.split("-");
  return parts.length === 3 ? `${parts[1]}/${parts[2]}` : iso;
}

function priceLabel(v: number): string {
  return v >= 100 ? Math.round(v).toString() : v.toFixed(1);
}

export default function GrgDivergenceChart({
  history,
  tops = [],
  bottoms = [],
}: {
  history: GrgHistoryEntry[];
  tops?: GrgEvent[];
  bottoms?: GrgEvent[];
}) {
  if (!history.length) {
    return (
      <div className="section" data-testid="grg-divergence-empty">
        <div className="section-header">
          <div className="section-title">YTD Divergence Field</div>
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

  // Left axis: shared z-axis, anchored to ±3σ but widened if data exceeds it.
  const zDomain = finiteDomain(
    history.flatMap((h) => [h.grg_z, h.spy_gamma_z, h.tlt_gamma_z]),
  );
  const hi = Math.max(
    3,
    zDomain ? Math.abs(zDomain.hi) : 3,
    zDomain ? Math.abs(zDomain.lo) : 3,
  );
  const yScale = linearScale([-hi, hi], [HEIGHT - PAD.bottom, PAD.top]);

  // Right axis: SPY price. Absent on legacy snapshots (no spy_price) — the
  // chart then degrades to σ-only with no price line / dots.
  const priceDomain = finiteDomain(history.map((h) => h.spy_price));
  const priceScale =
    priceDomain && priceDomain.hi > priceDomain.lo
      ? linearScale(
          [
            priceDomain.lo - (priceDomain.hi - priceDomain.lo) * 0.08,
            priceDomain.hi + (priceDomain.hi - priceDomain.lo) * 0.08,
          ],
          [HEIGHT - PAD.bottom, PAD.top],
        )
      : null;

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

  const spyPricePath = priceScale
    ? pathFromNullablePoints(
        history.map((h, i): [number, number] | null =>
          h.spy_price == null ? null : [xScale(i), priceScale(h.spy_price)],
        ),
      )
    : "";

  // Gate-confirmed event dots, placed on the SPY price line at the event date.
  const idxByDate = new Map(history.map((h, i) => [h.date, i]));
  const priceByDate = new Map(history.map((h) => [h.date, h.spy_price]));
  type Dot = { x: number; y: number; color: string; date: string };
  const eventDots: Dot[] = [];
  if (priceScale) {
    for (const [events, color] of [
      [tops, COLORS.top] as const,
      [bottoms, COLORS.bottom] as const,
    ]) {
      for (const ev of events) {
        const i = idxByDate.get(ev.date);
        const px = priceByDate.get(ev.date);
        if (i == null || px == null) continue;
        eventDots.push({
          x: xScale(i),
          y: priceScale(px),
          color,
          date: ev.date,
        });
      }
    }
  }

  const xTickIdx = dateTickIndices(history.length, 6);
  const sigmaTicks = [-3, 0, 3];
  const priceTicks = priceDomain
    ? [priceDomain.lo, (priceDomain.lo + priceDomain.hi) / 2, priceDomain.hi]
    : [];

  return (
    <div className="section" data-testid="grg-divergence-chart">
      <div className="section-header">
        <div className="section-title">YTD Divergence Field</div>
        <div
          style={{
            display: "flex",
            gap: 12,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <LegendSwatch color={COLORS.grg} label="GRG" />
          <LegendSwatch color={COLORS.spy} label="SPY γ" />
          <LegendSwatch color={COLORS.tlt} label="TLT γ" />
          {priceScale ? (
            <LegendSwatch color={COLORS.price} label="SPY $" />
          ) : null}
          <LegendSwatch color={COLORS.top} label="TOP-WATCH" />
          <LegendSwatch color={COLORS.bottom} label="BOTTOM-WATCH" />
        </div>
      </div>
      <div className="section-body" style={{ padding: "8px 12px 12px" }}>
        <svg
          role="img"
          aria-label="Year-to-date GRG divergence field with SPY price overlay"
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: "auto", display: "block" }}
        >
          <title>
            GRG, SPY/TLT gamma-z, and SPY price YTD with gate-confirmed
            top/bottom markers
          </title>

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

          {/* Right price axis ticks */}
          {priceScale &&
            priceTicks.map((p, k) => (
              <text
                key={`px${k}`}
                x={WIDTH - PAD.right + 6}
                y={priceScale(p) + 3}
                fontSize={9}
                fontFamily="var(--font-mono)"
                fill="var(--text-muted)"
                textAnchor="start"
              >
                {priceLabel(p)}
              </text>
            ))}

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

          {/* SPY price (context) sits behind the σ signal lines */}
          {spyPricePath ? (
            <path
              data-testid="grg-spy-price-line"
              d={spyPricePath}
              fill="none"
              stroke={COLORS.price}
              strokeWidth={1.4}
              strokeLinecap="round"
              opacity={0.9}
            />
          ) : null}

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

          {/* Gate-confirmed top/bottom dots on the SPY price line */}
          <g data-testid="grg-event-dots">
            {eventDots.map((d, k) => (
              <circle
                key={`dot${k}`}
                data-testid="grg-event-dot"
                cx={d.x}
                cy={d.y}
                r={4}
                fill={d.color}
                stroke="var(--bg-panel, #0b0e14)"
                strokeWidth={1.5}
              >
                <title>{`${d.date} — gate-confirmed watch (lead signal, not the exact turn)`}</title>
              </circle>
            ))}
          </g>
        </svg>
      </div>
    </div>
  );
}
