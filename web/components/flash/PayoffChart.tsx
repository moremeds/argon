import {
  payoffBreakpoints,
  payoffDomain,
  pnlAt,
} from "@/lib/flash/payoff";

import type { CandidateView } from "./view";

const W = 520;
const H = 196;
const M_L = 52;
const M_R = 14;
const M_T = 16;
const M_B = 28;
const IW = W - M_L - M_R;
const IH = H - M_T - M_B;

function fmtInt(n: number): string {
  return (n < 0 ? "−" : "+") + Math.abs(n).toLocaleString("en-US");
}

/**
 * P&L at expiry vs spot, per contract. Hand-rolled SVG.
 *
 * Renders NOTHING — not a placeholder, not an axis — when the structure is
 * unpriced, when either bound is unbounded, or when spot or a breakeven is
 * missing. An unbounded loss has no y-domain, and inventing one draws a floor
 * the position does not have; for this tenant that is a data fault to surface
 * elsewhere, not a shape to guess at.
 */
export function PayoffChart({ candidate }: { candidate: CandidateView }) {
  const { pricing, spot, legs } = candidate;
  if (pricing.kind !== "priced") return null;
  const { net, maxGain, maxLoss, breakevens } = pricing;
  if (maxGain == null || maxLoss == null) return null;
  const breakeven = breakevens[0];
  if (spot == null || breakeven == null || legs.length === 0) return null;

  const strikes = legs.map((l) => l.strike);
  const [xlo, xhi] = payoffDomain({ strikes, spot, breakeven });
  const ypad = 0.08 * (maxGain + maxLoss);
  const ylo = -maxLoss - ypad;
  const yhi = maxGain + ypad;
  const X = (s: number) => M_L + ((s - xlo) / (xhi - xlo)) * IW;
  const Y = (p: number) => M_T + ((yhi - p) / (yhi - ylo)) * IH;
  const y0 = Y(0);

  const curve = payoffBreakpoints({ strikes, breakeven, domain: [xlo, xhi] }).map(
    (s) => {
      const p = pnlAt(legs, net, s);
      return { x: X(s), y: Y(p), p };
    },
  );

  // Each segment is split at its sign change so the fill and the stroke never
  // straddle zero — a single green area crossing the axis reads as a profit
  // where there is a loss.
  type Pt = { x: number; y: number; p: number };
  const segments: [Pt, Pt][] = [];
  for (let i = 0; i < curve.length - 1; i += 1) {
    const a = curve[i];
    const b = curve[i + 1];
    if (a.p >= 0 === b.p >= 0) {
      segments.push([a, b]);
    } else {
      const t = (0 - a.p) / (b.p - a.p);
      const mid: Pt = { x: a.x + (b.x - a.x) * t, y: y0, p: 0 };
      segments.push([a, mid], [mid, b]);
    }
  }

  const gainsBelow = pnlAt(legs, net, xlo) > pnlAt(legs, net, xhi);
  const beLeft = X(breakeven) < X(spot);
  const strategy = candidate.strategy.replace(/_/g, " ");

  return (
    <svg
      viewBox={`0 0 ${W} ${H}`}
      width="100%"
      role="img"
      aria-label={
        `Profit and loss at expiry versus spot for the ${candidate.ticker} ` +
        `${strategy}. Maximum gain ${maxGain} dollars ` +
        `${gainsBelow ? "below" : "above"} the ${breakeven} breakeven, ` +
        `maximum loss ${maxLoss} dollars ${gainsBelow ? "above" : "below"} it, ` +
        `per contract.`
      }
    >
      <line
        x1={M_L}
        y1={Y(maxGain)}
        x2={W - M_R}
        y2={Y(maxGain)}
        stroke="var(--chart-grid)"
        strokeWidth="1"
      />
      <line
        x1={M_L}
        y1={Y(-maxLoss)}
        x2={W - M_R}
        y2={Y(-maxLoss)}
        stroke="var(--chart-grid)"
        strokeWidth="1"
      />
      <line
        x1={M_L}
        y1={y0}
        x2={W - M_R}
        y2={y0}
        stroke="var(--border-dim)"
        strokeWidth="1"
      />

      {segments.map(([p, q], i) => {
        const up = p.p + q.p >= 0;
        return (
          <g key={i}>
            <polygon
              points={`${p.x},${p.y} ${q.x},${q.y} ${q.x},${y0} ${p.x},${y0}`}
              fill={up ? "var(--fill-pos)" : "var(--fill-neg)"}
            />
            <line
              x1={p.x}
              y1={p.y}
              x2={q.x}
              y2={q.y}
              stroke={up ? "var(--positive)" : "var(--negative)"}
              strokeWidth="2"
              strokeLinecap="round"
            />
          </g>
        );
      })}

      {strikes
        .filter((k) => k > xlo && k < xhi)
        .map((k) => (
          <g key={k}>
            <line
              x1={X(k)}
              y1={M_T}
              x2={X(k)}
              y2={M_T + IH}
              stroke="var(--chart-grid)"
              strokeWidth="1"
            />
            <text
              x={X(k)}
              y={M_T + IH + 13}
              fill="var(--text-muted)"
              fontSize="10"
              textAnchor="middle"
            >
              {k.toFixed(2)}
            </text>
          </g>
        ))}

      <line
        x1={X(breakeven)}
        y1={M_T}
        x2={X(breakeven)}
        y2={M_T + IH}
        stroke="var(--warn)"
        strokeWidth="1"
        strokeDasharray="3 3"
      />
      <line
        x1={X(spot)}
        y1={M_T}
        x2={X(spot)}
        y2={M_T + IH}
        stroke="var(--text-secondary)"
        strokeWidth="1"
        strokeDasharray="2 4"
      />
      <text
        x={X(breakeven) + (beLeft ? -5 : 5)}
        y={M_T + 11}
        fill="var(--warn)"
        fontSize="10"
        textAnchor={beLeft ? "end" : "start"}
      >
        BE {breakeven.toFixed(2)}
      </text>
      <text
        x={X(spot) + (beLeft ? 5 : -5)}
        y={M_T + 11}
        fill="var(--text-secondary)"
        fontSize="10"
        textAnchor={beLeft ? "start" : "end"}
      >
        SPOT {spot.toFixed(2)}
      </text>

      <text
        x={M_L - 8}
        y={Y(maxGain) + 4}
        fill="var(--positive)"
        fontSize="10"
        fontWeight="700"
        textAnchor="end"
      >
        {fmtInt(maxGain)}
      </text>
      <text
        x={M_L - 8}
        y={y0 + 4}
        fill="var(--text-muted)"
        fontSize="10"
        textAnchor="end"
      >
        0
      </text>
      <text
        x={M_L - 8}
        y={Y(-maxLoss) + 4}
        fill="var(--negative)"
        fontSize="10"
        fontWeight="700"
        textAnchor="end"
      >
        {fmtInt(-maxLoss)}
      </text>
    </svg>
  );
}
