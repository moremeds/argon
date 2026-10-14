import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import {
  chartFrame,
  niceTicks,
  pathFromBand,
  pathFromPoints,
} from "@/lib/svgChart";

import {
  AXIS,
  COLOR,
  LABEL_TEXT,
  PARTS,
  RESEARCH_LABEL,
  SOURCE,
  complete,
  fmt,
  yearTicks,
  type FactorPoint,
  type FactorYear,
  type GoldFactor,
} from "./shared";

function xByIndex(n: number, f: ReturnType<typeof chartFrame>) {
  return f.x([0, Math.max(1, n - 1)]);
}

/** Each slope on its own axis: the units differ (% per bp against % per %), so one shared
 *  axis would flatten the yield slope into its zero line. `legs` selects which of the
 *  three factor slopes to draw (fixed canonical order, height follows the rendered
 *  count) — the rates tab renders `["yield"]` beside its own decompositions, under its
 *  own panel id/title; `id`/`title` default to the gold tab's identity. */
export function SensitivityPanel({
  last,
  legs,
  id = "gold-factor-sensitivity",
  title = "Gold sensitivity",
}: {
  last: FactorPoint;
  legs?: ("yield" | "dollar" | "haven")[];
  id?: string;
  title?: string;
}) {
  const rows = [
    {
      leg: "yield" as const,
      label: "Real yield · %/bp",
      b: last.b_r,
      lo: last.b_r_lo95,
      hi: last.b_r_hi95,
      color: COLOR.yield,
    },
    {
      leg: "dollar" as const,
      label: "Dollar · %/%",
      b: last.b_d,
      lo: last.b_d_lo95,
      hi: last.b_d_hi95,
      color: COLOR.dollar,
    },
    {
      leg: "haven" as const,
      label: "Haven · %/%",
      b: last.b_s,
      lo: last.b_s_lo95,
      hi: last.b_s_hi95,
      color: COLOR.haven,
    },
  ].filter((r) => legs?.includes(r.leg) ?? true);
  const W = 620;
  const RH = 64;
  return (
    <BoardPanel
      id={id}
      title={title}
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
                <text x={0} y={y + 10} fontSize={14} fill="var(--text-primary)">
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
                  {fmt(r.lo, 2)}
                </text>
                <text x={x(r.hi)} y={y + 18} {...AXIS} textAnchor="middle">
                  {fmt(r.hi, 2)}
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
        Dot = slope fitted over the past 252 trading days; bar = 95% interval ·
        through {last.obs_date} · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

export function ExplainedSharePanel({ data }: { data: GoldFactor }) {
  const pts = data.points.filter((p) => p.explained_share != null);
  const f = chartFrame(620, 240, { top: 10, right: 12, bottom: 22, left: 34 });
  const x = xByIndex(pts.length, f);
  const y = f.y([-0.4, 1]);
  const last = pts.at(-1);
  return (
    <BoardPanel
      id="gold-factor-explained"
      title="How much of gold's daily move 3 factors explain"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      <div className="chart">
        <svg {...f.svg} aria-label="Explained share, past 63 trading days">
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
            stroke={COLOR.sum}
            strokeWidth={1.5}
          />
          {yearTicks(pts.map((p) => p.obs_date)).map((t) => (
            <text key={t.label} x={x(t.i)} y={f.H - 6} {...AXIS}>
              {t.label}
            </text>
          ))}
        </svg>
      </div>
      <p className="cap">
        Dashed lines are the label thresholds: below{" "}
        {data.explained_low.toFixed(3)} &ldquo;explain little&rdquo;, above{" "}
        {data.explained_high.toFixed(3)} &ldquo;explain a lot&rdquo;.
        {last ? (
          <>
            {" "}
            Now {Math.round((last.explained_share as number) * 100)}% (
            {LABEL_TEXT[last.published_label ?? ""] ?? "not labelled yet"}).
          </>
        ) : null}{" "}
        {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

type Line = {
  key: string;
  label: string;
  color: string;
  values: number[];
  width?: number;
  dash?: string;
};

/** Running totals over one set of dates, one line each, zero line drawn. */
function CumLines({ lines, label }: { lines: Line[]; label: string }) {
  const all = lines.flatMap((l) => l.values);
  const n = Math.max(0, ...lines.map((l) => l.values.length));
  const f = chartFrame(620, 240, { top: 10, right: 12, bottom: 22, left: 34 });
  const lo = Math.min(0, ...all);
  const hi = Math.max(0, ...all);
  const x = xByIndex(n, f);
  const y = f.y([lo, hi]);
  return (
    <>
      <div className="lgd">
        {lines.map((l) => (
          <span key={l.key}>
            <i style={{ background: l.color }} />
            {l.label}
          </span>
        ))}
      </div>
      <div className="chart">
        <svg {...f.svg} aria-label={label}>
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
          {lines.map((l) => (
            <path
              key={l.key}
              d={pathFromPoints(l.values.map((v, i) => [x(i), y(v)]))}
              fill="none"
              stroke={l.color}
              strokeWidth={l.width ?? 1.4}
              strokeDasharray={l.dash}
            />
          ))}
        </svg>
      </div>
    </>
  );
}

function running(rows: FactorPoint[], pick: (r: FactorPoint) => number) {
  let acc = 0;
  return rows.map((r) => (acc += pick(r)));
}

function thisYear(data: GoldFactor) {
  const year = data.last_date.slice(0, 4);
  return complete(data.points).filter((p) => p.obs_date.startsWith(year));
}

const GOLD_LINE = { key: "gold", label: "Gold", color: COLOR.gold, width: 2 };

export function YearToDatePanel({ data }: { data: GoldFactor }) {
  const rows = thisYear(data);
  return (
    <BoardPanel
      id="gold-factor-ytd"
      title="Year to date, cumulative"
      questions={["Q4"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="running sum of each daily part"
    >
      <CumLines
        label="Year-to-date cumulative parts"
        lines={[
          { ...GOLD_LINE, values: running(rows, (r) => r.gold_change) },
          ...PARTS.map((p) => ({
            key: p.key,
            label: p.label,
            color: p.color,
            values: running(rows, (r) => r[p.key] ?? 0),
            dash:
              p.key === "unexplained_1" || p.key === "own_trailing_drift"
                ? "5 4"
                : undefined,
          })),
        ]}
      />
      <p className="cap">
        Percent (100 × log change), {rows.length} trading days ·{" "}
        {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

export function SlopeHistory({
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
  const f = chartFrame(620, 140, { top: 14, right: 12, bottom: 18, left: 40 });
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
        opacity={0.2}
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
      {yearTicks(rows.map((p) => p.obs_date)).map((t) => (
        <text key={t.label} x={x(t.i)} y={f.H - 4} {...AXIS}>
          {t.label}
        </text>
      ))}
    </svg>
  );
}

export function SensitivityHistoryPanel({ data }: { data: GoldFactor }) {
  return (
    <BoardPanel
      id="gold-factor-slope-history"
      title="Sensitivity history (shade = 95% interval)"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      <div className="chart">
        <SlopeHistory
          pts={data.points}
          k="b_d"
          label="Dollar · %/%"
          color={COLOR.dollar}
        />
        <SlopeHistory
          pts={data.points}
          k="b_r"
          label="Real yield · %/bp"
          color={COLOR.yield}
        />
      </div>
      <p className="cap">
        Each point is a fit over the 252 trading days to that date ·{" "}
        {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

/* ── Attribution review ── */

/** "Drift" is gold's average pace over the past year. When this year does not repeat it,
 *  the gap lands in "unexplained" and reads like a hole in the model. */
export function DriftVsGoldPanel({ data }: { data: GoldFactor }) {
  const rows = thisYear(data);
  const drift = running(rows, (r) => r.own_trailing_drift ?? 0);
  const gold = running(rows, (r) => r.gold_change);
  return (
    <BoardPanel
      id="gold-factor-drift"
      title="This year: drift vs actual gold"
      questions={["Q4"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="running sum of drift and of gold's daily change"
    >
      <CumLines
        label="This year, drift and actual gold, cumulative"
        lines={[
          { ...GOLD_LINE, values: gold },
          {
            key: "drift",
            label: "Drift",
            color: COLOR.drift,
            values: drift,
            dash: "5 4",
          },
        ]}
      />
      <p className="cap">
        Drift is gold&rsquo;s average pace over the past year. This year drift
        adds up to {fmt(drift.at(-1) ?? 0, 1)}, actual gold to{" "}
        {fmt(gold.at(-1) ?? 0, 1)} · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

export function RegroupPanel({ data }: { data: GoldFactor }) {
  const rows = thisYear(data);
  return (
    <BoardPanel
      id="gold-factor-regroup"
      title="Regrouped: 3 factors vs the rest"
      questions={["Q4"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="3 factors = real yield + dollar + haven; the rest = drift + unexplained"
    >
      <CumLines
        label="This year, 3 factors and the rest, cumulative"
        lines={[
          { ...GOLD_LINE, values: running(rows, (r) => r.gold_change) },
          {
            key: "sum",
            label: "3 factors",
            color: COLOR.sum,
            values: running(
              rows,
              (r) =>
                (r.real_yield_part ?? 0) +
                (r.dollar_part ?? 0) +
                (r.haven_part ?? 0),
            ),
          },
          {
            key: "rest",
            label: "The rest",
            color: COLOR.drift,
            values: running(
              rows,
              (r) => (r.own_trailing_drift ?? 0) + (r.unexplained_1 ?? 0),
            ),
            dash: "5 4",
          },
        ]}
      />
      <p className="cap">
        Regrouped only, not refit. The two groups still add up to gold&rsquo;s
        move · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

export function AttributionTable({ years }: { years: FactorYear[] }) {
  const n = (v: number) => fmt(v, 1);
  return (
    <details className="data-details" data-testid="gold-factor-year-table">
      <summary>Numbers (100 × log change)</summary>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Year</th>
              <th className="num">Gold</th>
              <th className="num">Real yield</th>
              <th className="num">Dollar</th>
              <th className="num">Haven</th>
              <th className="num">3 factors</th>
              <th className="num">Drift</th>
              <th className="num">Unexplained</th>
              <th className="num">The rest</th>
            </tr>
          </thead>
          <tbody>
            {[...years].reverse().map((y) => (
              <tr key={y.year}>
                <td>
                  {y.year}
                  {y.partial_year ? " (partial)" : ""}
                </td>
                <td className="num">{n(y.gold_change)}</td>
                <td className="num">{n(y.real_yield_part)}</td>
                <td className="num">{n(y.dollar_part)}</td>
                <td className="num">{n(y.haven_part)}</td>
                <td className="num">
                  {n(y.real_yield_part + y.dollar_part + y.haven_part)}
                </td>
                <td className="num">{n(y.own_trailing_drift)}</td>
                <td className="num">{n(y.unexplained)}</td>
                <td className="num">
                  {n(y.own_trailing_drift + y.unexplained)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
    </details>
  );
}
