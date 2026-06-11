"use client";

import {
  finiteDomain,
  linearScale,
  niceTicks,
  pathFromPoints,
} from "@/lib/svgChart";
import type { GexHistoryEntry } from "@/lib/regime/useGex";

const WIDTH = 880;
const HEIGHT = 260;
const PAD = { top: 16, right: 64, bottom: 36, left: 64 };

const COLORS = {
  netGex: "var(--accent-bg, #05AD98)",
  flip: "var(--accent-warm, #F5A623)",
  spot: "var(--text-primary)",
  zero: "var(--border-dim)",
  grid: "rgba(148,163,184,0.08)",
};

function LegendSwatch({
  color,
  label,
  dashed,
}: {
  color: string;
  label: string;
  dashed?: boolean;
}) {
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
      <svg width="20" height="6" aria-hidden="true">
        <line
          x1={0}
          x2={20}
          y1={3}
          y2={3}
          stroke={color}
          strokeWidth={2}
          strokeDasharray={dashed ? "3 2" : undefined}
        />
      </svg>
      {label}
    </span>
  );
}

/** Pick ~5 evenly-spaced indices to label on the x-axis. */
function dateTickIndices(n: number, count: number = 5): number[] {
  if (n <= count) return Array.from({ length: n }, (_, i) => i);
  const step = (n - 1) / (count - 1);
  return Array.from({ length: count }, (_, i) => Math.round(i * step));
}

/** "YYYY-MM-DD" → "MM/DD". */
function shortDate(iso: string): string {
  const [, m, d] = iso.split("-");
  return `${m}/${d}`;
}

export function HistoryChart({
  history,
  ticker,
}: {
  history: GexHistoryEntry[];
  ticker: string;
}) {
  if (!history.length) {
    return (
      <div className="section" data-testid="gex-history-empty">
        <div className="section-header">
          <div className="section-title">
            {ticker} — 90-Day GEX History
          </div>
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

  const netGexD = finiteDomain(history.map((h) => h.net_gex));
  const priceD = finiteDomain(history.flatMap((h) => [h.spot, h.gex_flip]));

  const yGex = netGexD
    ? linearScale([netGexD.lo, netGexD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;
  const yPrice = priceD
    ? linearScale([priceD.lo, priceD.hi], [HEIGHT - PAD.bottom, PAD.top])
    : null;

  const netGexPath =
    yGex == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.net_gex == null ? null : [xScale(i), yGex(h.net_gex)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const flipPath =
    yPrice == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.gex_flip == null ? null : [xScale(i), yPrice(h.gex_flip)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const spotPath =
    yPrice == null
      ? ""
      : pathFromPoints(
          history
            .map((h, i): [number, number] | null =>
              h.spot == null ? null : [xScale(i), yPrice(h.spot)],
            )
            .filter((p): p is [number, number] => p != null),
        );

  const xTickIdx = dateTickIndices(history.length, 5);
  const leftTicks = netGexD ? niceTicks(netGexD.lo, netGexD.hi, 4) : [];
  const rightTicks = priceD ? niceTicks(priceD.lo, priceD.hi, 4) : [];

  return (
    <div className="section" data-testid="gex-history-chart">
      <div className="section-header">
        <div className="section-title">
          {ticker} — 90-Day GEX History
        </div>
        <div
          style={{
            display: "flex",
            gap: 14,
            flexWrap: "wrap",
            alignItems: "center",
          }}
        >
          <LegendSwatch color={COLORS.netGex} label="NET GEX" />
          <LegendSwatch color={COLORS.flip} label="GEX FLIP" dashed />
          <LegendSwatch color={COLORS.spot} label="SPOT" />
        </div>
      </div>
      <div className="section-body" style={{ padding: "8px 12px 12px" }}>
        <svg
          role="img"
          aria-label={`${ticker} 90-day GEX history`}
          viewBox={`0 0 ${WIDTH} ${HEIGHT}`}
          style={{ width: "100%", height: HEIGHT, display: "block" }}
        >
          <title>{`${ticker} — net GEX, flip migration, spot`}</title>

          {/* Zero line for net GEX. */}
          {yGex != null &&
            netGexD != null &&
            netGexD.lo <= 0 &&
            netGexD.hi >= 0 && (
              <line
                x1={PAD.left}
                x2={WIDTH - PAD.right}
                y1={yGex(0)}
                y2={yGex(0)}
                stroke={COLORS.zero}
                strokeDasharray="2 3"
              />
            )}

          {/* Left y-axis (net GEX) ticks. */}
          {yGex &&
            leftTicks.map((v) => {
              const y = yGex(v);
              return (
                <g key={`L${v}`}>
                  <line
                    x1={PAD.left - 4}
                    x2={WIDTH - PAD.right}
                    y1={y}
                    y2={y}
                    stroke={COLORS.grid}
                  />
                  <text
                    x={PAD.left - 6}
                    y={y + 3}
                    textAnchor="end"
                    fontSize={9}
                    fontFamily="var(--font-mono)"
                    fill={COLORS.netGex}
                  >
                    {Math.abs(v) >= 1000
                      ? `${(v / 1000).toFixed(1)}K`
                      : v.toFixed(0)}
                  </text>
                </g>
              );
            })}

          {/* Right y-axis (price band). */}
          {yPrice &&
            rightTicks.map((v) => {
              const y = yPrice(v);
              return (
                <text
                  key={`R${v}`}
                  x={WIDTH - PAD.right + 6}
                  y={y + 3}
                  textAnchor="start"
                  fontSize={9}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-secondary)"
                >
                  {v.toFixed(0)}
                </text>
              );
            })}

          {/* X-axis date labels. */}
          {xTickIdx.map((i) => {
            const x = xScale(i);
            const entry = history[i];
            if (!entry?.date) return null;
            return (
              <g key={`X${i}`}>
                <line
                  x1={x}
                  x2={x}
                  y1={HEIGHT - PAD.bottom}
                  y2={HEIGHT - PAD.bottom + 4}
                  stroke="var(--text-muted)"
                />
                <text
                  x={x}
                  y={HEIGHT - PAD.bottom + 16}
                  textAnchor="middle"
                  fontSize={10}
                  fontFamily="var(--font-mono)"
                  fill="var(--text-secondary)"
                >
                  {shortDate(entry.date)}
                </text>
              </g>
            );
          })}

          <path
            d={netGexPath}
            fill="none"
            stroke={COLORS.netGex}
            strokeWidth={1.5}
          />
          <path
            d={flipPath}
            fill="none"
            stroke={COLORS.flip}
            strokeWidth={1.2}
            strokeDasharray="3 2"
          />
          <path
            d={spotPath}
            fill="none"
            stroke={COLORS.spot}
            strokeWidth={1.2}
          />
        </svg>
      </div>
    </div>
  );
}
