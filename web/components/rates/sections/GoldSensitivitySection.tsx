import {
  AXIS,
  COLOR,
  RESEARCH_LABEL,
  SOURCE,
  fmt,
  type FactorPoint,
} from "@/components/macro/goldFactor/shared";

import { RatesSection } from "../RatesSection";

/**
 * The real-yield row of the gold tab's `SensitivityPanel`
 * (`components/macro/goldFactor/GoldFactorPanels.tsx`), alone on tab 02. That
 * panel keeps each slope on its own axis precisely because %/bp and %/% cannot
 * share a scale, so the real-yield row loses nothing by standing beside the 10Y
 * decomposition it answers. The fit is computed server-side into
 * `gold_factor_daily`; this renders the stored estimate on the same zero-centred
 * dot-and-bar grammar, so the two pages cannot disagree about the same number.
 * Live-only by construction: `/api/gold/factor` takes no `as_of`, and the page
 * does not pass a factor under replay, so today's fit can never read as history.
 */
export function GoldSensitivitySection({ last }: { last: FactorPoint }) {
  if (last.b_r == null || last.b_r_lo95 == null || last.b_r_hi95 == null) {
    return null;
  }
  const b = last.b_r;
  const lo = last.b_r_lo95;
  const hi = last.b_r_hi95;
  const W = 620;
  const m = Math.max(Math.abs(lo), Math.abs(hi)) * 1.15;
  const x = (v: number) => 150 + ((v + m) / (2 * m)) * (W - 160);
  const y = 26;
  return (
    <RatesSection
      id="gold-real-yield-sensitivity"
      title="Gold · real-yield sensitivity"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      <div className="chart">
        <svg
          viewBox={`0 0 ${W} 64`}
          width="100%"
          role="img"
          aria-label="Gold's sensitivity to the 10Y real yield with 95% interval"
        >
          <text x={0} y={y - 8} {...AXIS} fill="var(--text-secondary)">
            Real yield · %/bp
          </text>
          <text x={0} y={y + 10} fontSize={14} fill="var(--text-primary)">
            {fmt(b, 3)}
          </text>
          <line
            x1={x(0)}
            x2={x(0)}
            y1={y - 12}
            y2={y + 12}
            stroke="var(--border-dim)"
            strokeDasharray="3 3"
          />
          <line
            x1={x(lo)}
            x2={x(hi)}
            y1={y}
            y2={y}
            stroke={COLOR.yield}
            strokeWidth={3}
            strokeLinecap="round"
            opacity={0.55}
          />
          <circle cx={x(b)} cy={y} r={5} fill={COLOR.yield} />
          <text x={x(lo)} y={y + 18} {...AXIS} textAnchor="middle">
            {fmt(lo, 2)}
          </text>
          <text x={x(hi)} y={y + 18} {...AXIS} textAnchor="middle">
            {fmt(hi, 2)}
          </text>
          {lo < 0 && hi > 0 ? (
            <text x={W} y={y - 8} {...AXIS} textAnchor="end">
              interval crosses zero
            </text>
          ) : null}
        </svg>
      </div>
      <p className="cap">
        Dot = slope fitted over the past 252 trading days; bar = 95% interval ·
        through {last.obs_date} · {RESEARCH_LABEL}
      </p>
    </RatesSection>
  );
}
