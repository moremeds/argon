import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import {
  chartFrame,
  niceTicks,
  pathFromBand,
  pathFromPoints,
} from "@/lib/svgChart";

import { MoveBreakdownPanel, YearlyBreakdownPanel } from "./GoldFactorToggles";
import {
  LABEL_TEXT,
  PARTS,
  RESEARCH_LABEL,
  complete,
  fmt,
  type FactorPoint,
  type GoldFactor,
} from "./shared";

const SOURCE = "/api/gold/factor · gold_factor_daily";
const AXIS = { fontSize: 10, fill: "var(--text-muted)" } as const;

function xByIndex(n: number, f: ReturnType<typeof chartFrame>) {
  return f.x([0, Math.max(1, n - 1)]);
}

function yearTicks(points: FactorPoint[]): { i: number; label: string }[] {
  const out: { i: number; label: string }[] = [];
  points.forEach((p, i) => {
    const y = p.obs_date.slice(0, 4);
    // a window that starts late in a year would print that label on top of the next one
    const first = i === 0 && p.obs_date.slice(5, 7) <= "03";
    if (first || (i > 0 && points[i - 1].obs_date.slice(0, 4) !== y))
      out.push({ i, label: y });
  });
  return out;
}

/** Each slope on its own axis: the units differ (% per bp against % per %), so one shared
 *  axis would flatten the yield slope into its zero line. */
function SensitivityPanel({ last }: { last: FactorPoint }) {
  const rows = [
    {
      label: "Real yield (% per bp)",
      b: last.b_r,
      lo: last.b_r_lo95,
      hi: last.b_r_hi95,
      color: PARTS[0].color,
    },
    {
      label: "Dollar (% per %)",
      b: last.b_d,
      lo: last.b_d_lo95,
      hi: last.b_d_hi95,
      color: PARTS[1].color,
    },
    {
      label: "Safe haven (% per %)",
      b: last.b_s,
      lo: last.b_s_lo95,
      hi: last.b_s_hi95,
      color: PARTS[2].color,
    },
  ];
  const W = 620;
  const RH = 74;
  return (
    <BoardPanel
      id="gold-factor-sensitivity"
      title="Gold's sensitivity, last 252 days"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      <div className="chart">
        <svg
          viewBox={`0 0 ${W} ${RH * rows.length}`}
          width="100%"
          role="img"
          aria-label="Sensitivities with 95% intervals"
        >
          {rows.map((r, k) => {
            if (r.b == null || r.lo == null || r.hi == null) return null;
            const m = Math.max(Math.abs(r.lo), Math.abs(r.hi)) * 1.15;
            const x = (v: number) => 150 + ((v + m) / (2 * m)) * (W - 160);
            const y = k * RH + 26;
            const crosses = r.lo < 0 && r.hi > 0;
            return (
              <g key={r.label}>
                <text x={0} y={y - 8} {...AXIS} fill="var(--text-secondary)">
                  {r.label}
                </text>
                <text x={0} y={y + 8} fontSize={13} fill="var(--text-primary)">
                  {fmt(r.b, 3)}
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
                  x1={x(r.lo)}
                  x2={x(r.hi)}
                  y1={y}
                  y2={y}
                  stroke={r.color}
                  strokeWidth={3}
                  strokeLinecap="round"
                  opacity={0.55}
                />
                <circle cx={x(r.b)} cy={y} r={5} fill={r.color} />
                <text x={x(r.lo)} y={y + 18} {...AXIS} textAnchor="middle">
                  {r.lo.toFixed(2)}
                </text>
                <text x={x(r.hi)} y={y + 18} {...AXIS} textAnchor="middle">
                  {r.hi.toFixed(2)}
                </text>
                {crosses ? (
                  <text x={W} y={y - 8} {...AXIS} textAnchor="end">
                    interval crosses zero
                  </text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="cap">
        Dot = fitted slope, bar = 95% interval · as of {last.obs_date} ·{" "}
        {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

function ExplainedSharePanel({ data }: { data: GoldFactor }) {
  const pts = data.points.filter((p) => p.explained_share != null);
  const f = chartFrame(620, 260, { top: 10, right: 12, bottom: 22, left: 34 });
  const x = xByIndex(pts.length, f);
  const y = f.y([-0.4, 1]);
  const last = pts.at(-1);
  return (
    <BoardPanel
      id="gold-factor-explained"
      title="How much of gold's daily moves the three factors explain"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      <div className="chart">
        <svg {...f.svg} aria-label="Explained share over 63 days">
          {[0, 0.5, 1].map((t) => (
            <text
              key={t}
              x={f.M.left - 4}
              y={y(t) + 3}
              {...AXIS}
              textAnchor="end"
            >{`${t * 100}%`}</text>
          ))}
          {[data.explained_low, data.explained_high].map((t) => (
            <line
              key={t}
              x1={f.M.left}
              x2={f.W - f.M.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--text-muted)"
              strokeDasharray="4 4"
            />
          ))}
          <path
            d={pathFromPoints(
              pts.map((p, i) => [x(i), y(p.explained_share as number)]),
            )}
            fill="none"
            stroke="var(--text-primary)"
            strokeWidth={1.4}
          />
          {yearTicks(pts).map((t) => (
            <text key={t.label} x={x(t.i)} y={f.H - 6} {...AXIS}>
              {t.label}
            </text>
          ))}
        </svg>
      </div>
      <p className="cap">
        Share of the last 63 days&apos; variation the fit explains. Below{" "}
        {Math.round(data.explained_low * 100)}%: explains little; above{" "}
        {Math.round(data.explained_high * 100)}% with both slopes negative:
        explains much.
        {last ? (
          <>
            {" "}
            Now {Math.round((last.explained_share as number) * 100)}% —{" "}
            {LABEL_TEXT[last.published_label ?? ""] ?? "not yet labelled"}.
          </>
        ) : null}
      </p>
    </BoardPanel>
  );
}

function YearToDatePanel({ data }: { data: GoldFactor }) {
  const year = data.last_date.slice(0, 4);
  const rows = complete(data.points).filter((p) => p.obs_date.startsWith(year));
  const series = [
    {
      key: "gold_change",
      label: "Gold",
      color: "var(--text-primary)",
    } as const,
    ...PARTS,
  ];
  const cum = series.map((s) => {
    let acc = 0;
    return rows.map((r) => (acc += (r[s.key] as number) ?? 0));
  });
  const all = cum.flat();
  const f = chartFrame(620, 260, { top: 10, right: 12, bottom: 22, left: 34 });
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const x = xByIndex(rows.length, f);
  const y = f.y([lo, hi]);
  return (
    <BoardPanel
      id="gold-factor-ytd"
      title={`Running total since ${year}-01-01`}
      questions={["Q4"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="cumulative sum of each daily part"
    >
      <div className="lgd">
        {series.map((s) => (
          <span key={s.key}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
      </div>
      <div className="chart">
        <svg {...f.svg} aria-label="Year-to-date running totals">
          {niceTicks(lo, hi, 5)
            .filter((t) => t >= lo && t <= hi)
            .map((t) => (
              <g key={t}>
                <line
                  x1={f.M.left}
                  x2={f.W - f.M.right}
                  y1={y(t)}
                  y2={y(t)}
                  stroke="var(--border-dim)"
                  strokeWidth={t === 0 ? 1 : 0.4}
                />
                <text x={f.M.left - 4} y={y(t) + 3} {...AXIS} textAnchor="end">
                  {t}
                </text>
              </g>
            ))}
          {series.map((s, k) => (
            <path
              key={s.key}
              d={pathFromPoints(cum[k].map((v, i) => [x(i), y(v)]))}
              fill="none"
              stroke={s.color}
              strokeWidth={s.key === "gold_change" ? 2 : 1.3}
              strokeDasharray={
                s.key === "unexplained_1" || s.key === "own_trailing_drift"
                  ? "5 4"
                  : undefined
              }
            />
          ))}
        </svg>
      </div>
      <p className="cap">
        Percent (100 × log change), {rows.length} days · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

function SlopeHistory({
  pts,
  k,
  label,
  color,
}: {
  pts: FactorPoint[];
  k: "b_d" | "b_r";
  label: string;
  color: string;
}) {
  const rows = pts.filter((p) => p[k] != null);
  const lo = rows.map((p) => p[`${k}_lo95`] as number);
  const hi = rows.map((p) => p[`${k}_hi95`] as number);
  const f = chartFrame(620, 150, { top: 14, right: 12, bottom: 18, left: 40 });
  const x = xByIndex(rows.length, f);
  const y = f.y([Math.min(0, ...lo), Math.max(0, ...hi)]);
  return (
    <svg {...f.svg} aria-label={label}>
      <text x={f.M.left} y={10} {...AXIS} fill="var(--text-secondary)">
        {label}
      </text>
      <path
        d={pathFromBand(
          hi.map((v, i) => [x(i), y(v)]),
          lo.map((v, i) => [x(i), y(v)]),
        )}
        fill={color}
        opacity={0.18}
      />
      <line
        x1={f.M.left}
        x2={f.W - f.M.right}
        y1={y(0)}
        y2={y(0)}
        stroke="var(--text-muted)"
        strokeDasharray="3 3"
      />
      <text x={f.M.left - 4} y={y(0) + 3} {...AXIS} textAnchor="end">
        0
      </text>
      <path
        d={pathFromPoints(rows.map((p, i) => [x(i), y(p[k] as number)]))}
        fill="none"
        stroke={color}
        strokeWidth={1.4}
      />
      {yearTicks(rows).map((t) => (
        <text key={t.label} x={x(t.i)} y={f.H - 4} {...AXIS}>
          {t.label}
        </text>
      ))}
    </svg>
  );
}

function SensitivityHistoryPanel({ data }: { data: GoldFactor }) {
  return (
    <BoardPanel
      id="gold-factor-slope-history"
      title="Sensitivity history"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      <div className="chart">
        <SlopeHistory
          pts={data.points}
          k="b_d"
          label="Dollar, % per %"
          color={PARTS[1].color}
        />
        <SlopeHistory
          pts={data.points}
          k="b_r"
          label="Real yield, % per bp"
          color={PARTS[0].color}
        />
      </div>
      <p className="cap">
        Shade = 95% interval of each 252-day fit · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

/**
 * The gold factor model: how much of gold's daily move the 10-year real yield, the dollar
 * and the safe-haven spread explain, and each day's move split into those parts. Live only:
 * the endpoint takes no date, so under a replayed observation date it would answer about
 * today.
 */
export function GoldFactorBand({ data }: { data: GoldFactor }) {
  const last = data.points.at(-1);
  return (
    <section data-testid="gold-factor-band">
      <div className="sec-title">
        <h2>What moved gold</h2>
      </div>
      <p className="sec-sub">
        Gold&apos;s daily move split into the 10-year real yield, the dollar and
        the safe-haven spread, from a rolling 252-day fit. {RESEARCH_LABEL}.
      </p>
      <div className="grid g2">
        {last ? <SensitivityPanel last={last} /> : null}
        <ExplainedSharePanel data={data} />
      </div>
      <div className="grid g2" style={{ marginTop: 12 }}>
        <MoveBreakdownPanel data={data} />
        <YearToDatePanel data={data} />
      </div>
      <div className="grid g2" style={{ marginTop: 12, marginBottom: 24 }}>
        <YearlyBreakdownPanel years={data.years} />
        <SensitivityHistoryPanel data={data} />
      </div>
    </section>
  );
}
