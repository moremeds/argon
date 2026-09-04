import type { GammaLevel } from "./view";

const W = 360;
const ROW_H = 24;
const BAR_X = 132;
const BAR_W = 176;
const CX = BAR_X + BAR_W / 2;
const BAR_H = 13;

function fmtInt(n: number): string {
  return (n < 0 ? "−" : "+") + Math.abs(n).toLocaleString("en-US");
}

/**
 * Dealer gamma per strike, as diverging horizontal bars.
 *
 * A bar is its size; its side of the axis is its sign. Left of zero is
 * negative gamma, where hedging amplifies a move rather than damping it — the
 * caption says so in words because side-of-axis alone is a colour argument.
 *
 * Duplicate `(strike, label)` rows arrive from argon's own GEX tables (the
 * same level shows up under two roles); first occurrence wins, because a
 * repeated bar reads as twice the exposure.
 */
export function GammaBars({
  ticker,
  spot,
  levels,
}: {
  ticker: string;
  spot?: string | number;
  levels: GammaLevel[];
}) {
  const rows: GammaLevel[] = [];
  const seen = new Set<string>();
  for (const level of levels) {
    const key = `${level.strike}|${level.label}`;
    if (seen.has(key)) continue;
    seen.add(key);
    rows.push(level);
  }
  if (rows.length === 0) return null;

  const height = rows.length * ROW_H + 14;
  const maxAbs = Math.max(1, ...rows.map((r) => Math.abs(r.value)));

  return (
    <svg
      viewBox={`0 0 ${W} ${height}`}
      width="100%"
      role="img"
      aria-label={
        `Dealer gamma by strike for ${ticker}` +
        (spot == null ? "" : `, spot ${spot}`) +
        `. Bars left of the zero axis are negative gamma, bars right are positive.`
      }
    >
      <line
        x1={CX}
        y1={4}
        x2={CX}
        y2={rows.length * ROW_H + 2}
        stroke="var(--border-dim)"
        strokeWidth="1"
      />
      {rows.map((r, i) => {
        const y = i * ROW_H + 4;
        const w = (Math.abs(r.value) / maxAbs) * (BAR_W / 2 - 4);
        const pos = r.value >= 0;
        return (
          <g key={`${r.strike}|${r.label}`}>
            <text x={0} y={y + 10} fill="var(--text-primary)" fontSize="11" fontWeight="700">
              {r.strike.toFixed(2)}
            </text>
            <text x={58} y={y + 10} fill="var(--text-muted)" fontSize="9.5">
              {r.label}
            </text>
            {r.value === 0 ? (
              <rect x={CX - 1} y={y} width={2} height={BAR_H} fill="var(--text-muted)" />
            ) : (
              <rect
                x={pos ? CX + 1 : CX - 1 - w}
                y={y}
                width={w}
                height={BAR_H}
                rx="1.5"
                fill={pos ? "var(--positive)" : "var(--negative)"}
                opacity="0.85"
              />
            )}
            <text
              x={W}
              y={y + 10}
              fill={
                r.value === 0
                  ? "var(--text-muted)"
                  : pos
                    ? "var(--positive)"
                    : "var(--negative)"
              }
              fontSize="10"
              fontWeight="700"
              textAnchor="end"
            >
              {r.value === 0 ? "0" : fmtInt(r.value)}
            </text>
          </g>
        );
      })}
      <text
        x={CX}
        y={rows.length * ROW_H + 12}
        fill="var(--text-muted)"
        fontSize="9"
        textAnchor="middle"
      >
        − short gamma · 0 · long gamma +
      </text>
    </svg>
  );
}
