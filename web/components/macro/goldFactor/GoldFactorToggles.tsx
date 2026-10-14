"use client";

import { useState } from "react";

import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import { chartFrame, niceTicks } from "@/lib/svgChart";

import {
  AXIS,
  COLOR,
  PARTS,
  RESEARCH_LABEL,
  complete,
  fmt,
  sumParts,
  type FactorYear,
  type GoldFactor,
} from "./shared";

export function Toggle<T extends string>({
  options,
  value,
  onChange,
  label,
}: {
  options: readonly { id: T; text: string }[];
  value: T;
  onChange: (v: T) => void;
  label: string;
}) {
  return (
    <span
      role="group"
      aria-label={label}
      style={{ display: "inline-flex", gap: 4, marginBottom: 6 }}
    >
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          aria-pressed={o.id === value}
          onClick={() => onChange(o.id)}
          style={{
            font: "600 10px/1.6 var(--font-mono), monospace",
            letterSpacing: 1,
            padding: "2px 8px",
            borderRadius: 4,
            border: "1px solid var(--border-dim)",
            background:
              o.id === value ? "var(--bg-panel-raised)" : "transparent",
            color: o.id === value ? "var(--text-primary)" : "var(--text-muted)",
            cursor: "pointer",
          }}
        >
          {o.text}
        </button>
      ))}
    </span>
  );
}

export const WINDOWS = [
  { id: "week", text: "1W", rows: 5 },
  { id: "month", text: "1M", rows: 21 },
  { id: "ytd", text: "YTD", rows: 0 },
] as const;
export type WindowId = (typeof WINDOWS)[number]["id"];

/** Waterfall: each part steps from where the previous one ended, and the last bar is gold's
 *  own change, which the parts add up to exactly. */
export function MoveBreakdownPanel({ data }: { data: GoldFactor }) {
  const [win, setWin] = useState<WindowId>("month");
  const rows = complete(data.points);
  const w = WINDOWS.find((o) => o.id === win)!;
  const year = data.last_date.slice(0, 4);
  const picked = w.rows
    ? rows.slice(-w.rows)
    : rows.filter((r) => r.obs_date.startsWith(year));
  const s = sumParts(picked);
  const steps = PARTS.map((p) => s[p.key]);
  const bars: {
    label: string;
    color: string;
    from: number;
    to: number;
    v: number;
  }[] = PARTS.map((p, i) => {
    const from = steps.slice(0, i).reduce((a, b) => a + b, 0);
    return {
      label: p.label,
      color: p.color,
      from,
      to: from + steps[i],
      v: steps[i],
    };
  });
  bars.push({
    label: "Gold",
    color: COLOR.gold,
    from: 0,
    to: s.gold_change,
    v: s.gold_change,
  });
  const ends = bars.flatMap((b) => [b.from, b.to]);
  const lo = Math.min(0, ...ends);
  const hi = Math.max(0, ...ends);
  const f = chartFrame(620, 270, { top: 16, right: 8, bottom: 30, left: 34 });
  const y = f.y([lo, hi]);
  const bw = (f.W - f.M.left - f.M.right) / bars.length;
  return (
    <BoardPanel
      id="gold-factor-breakdown"
      title="What made up gold's move"
      questions={["Q4"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="sum of daily parts in the window; the parts add up to gold's change"
    >
      <Toggle label="Window" options={WINDOWS} value={win} onChange={setWin} />
      <div className="chart">
        <svg {...f.svg} aria-label="What moved gold">
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
          {bars.map((b, i) => {
            const x0 = f.M.left + i * bw + bw * 0.15;
            const top = y(Math.max(b.from, b.to));
            return (
              <g key={b.label}>
                <rect
                  x={x0}
                  y={top}
                  width={bw * 0.7}
                  height={Math.max(1, Math.abs(y(b.from) - y(b.to)))}
                  fill={b.color}
                  opacity={b.label === "Gold" ? 0.95 : 0.8}
                />
                <text
                  x={x0 + bw * 0.35}
                  y={top - 4}
                  {...AXIS}
                  fill="var(--text-secondary)"
                  textAnchor="middle"
                >
                  {fmt(b.v, 1)}
                </text>
                <text
                  x={x0 + bw * 0.35}
                  y={f.H - 14}
                  {...AXIS}
                  textAnchor="middle"
                >
                  {b.label}
                </text>
              </g>
            );
          })}
        </svg>
      </div>
      <p className="cap">
        Percent (100 × log change), {picked.length} trading days through{" "}
        {data.last_date} · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

const VIEWS = [
  { id: "grouped", text: "3 factors vs rest" },
  { id: "all", text: "All 5" },
] as const;
type ViewId = (typeof VIEWS)[number]["id"];

function segments(y: FactorYear, view: ViewId) {
  const factors = y.real_yield_part + y.dollar_part + y.haven_part;
  const rest = y.own_trailing_drift + y.unexplained;
  return view === "grouped"
    ? [
        { label: "3 factors", color: COLOR.sum, v: factors },
        { label: "The rest", color: COLOR.drift, v: rest },
      ]
    : [
        { label: PARTS[0].label, color: PARTS[0].color, v: y.real_yield_part },
        { label: PARTS[1].label, color: PARTS[1].color, v: y.dollar_part },
        { label: PARTS[2].label, color: PARTS[2].color, v: y.haven_part },
        {
          label: PARTS[3].label,
          color: PARTS[3].color,
          v: y.own_trailing_drift,
        },
        { label: PARTS[4].label, color: PARTS[4].color, v: y.unexplained },
      ];
}

/** Stacked by sign: positive parts build up from zero, negative ones down, and the dot is
 *  gold's own change for the year. "The rest" = drift + unexplained — a regrouping, not a new fit. */
export function YearlyBreakdownPanel({ years }: { years: FactorYear[] }) {
  const [view, setView] = useState<ViewId>("grouped");
  const stacks = years.map((yr) => {
    let up = 0;
    let down = 0;
    return segments(yr, view).map((s) => {
      const from = s.v >= 0 ? up : down;
      if (s.v >= 0) up += s.v;
      else down += s.v;
      return { ...s, from, to: from + s.v };
    });
  });
  const ends = stacks
    .flat()
    .flatMap((s) => [s.from, s.to])
    .concat(years.map((y) => y.gold_change));
  const lo = Math.min(0, ...ends);
  const hi = Math.max(0, ...ends);
  const f = chartFrame(620, 270, { top: 10, right: 8, bottom: 22, left: 34 });
  const y = f.y([lo, hi]);
  const bw = (f.W - f.M.left - f.M.right) / Math.max(1, years.length);
  const legend = segments(years[0] ?? ({} as FactorYear), view);
  return (
    <BoardPanel
      id="gold-factor-yearly"
      title="Each year, split"
      questions={["Q4"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source="sum of daily parts per year (/api/gold/factor years)"
    >
      <Toggle label="View" options={VIEWS} value={view} onChange={setView} />
      <div className="lgd">
        {legend.map((s) => (
          <span key={s.label}>
            <i style={{ background: s.color }} />
            {s.label}
          </span>
        ))}
        <span>
          <i
            style={{
              background: COLOR.gold,
              width: 6,
              height: 6,
              borderRadius: 3,
            }}
          />
          Gold
        </span>
      </div>
      <div className="chart">
        <svg {...f.svg} aria-label="Each year, split">
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
          {years.map((yr, i) => {
            const x0 = f.M.left + i * bw + bw * 0.15;
            return (
              <g key={yr.year} opacity={yr.partial_year ? 0.6 : 1}>
                {stacks[i].map((s) => (
                  <rect
                    key={s.label}
                    x={x0}
                    y={y(Math.max(s.from, s.to))}
                    width={bw * 0.7}
                    height={Math.abs(y(s.from) - y(s.to))}
                    fill={s.color}
                  />
                ))}
                <circle
                  cx={x0 + bw * 0.35}
                  cy={y(yr.gold_change)}
                  r={2.6}
                  fill={COLOR.gold}
                  stroke="var(--bg-panel)"
                />
                {i % 2 === 0 ? (
                  <text
                    x={x0 + bw * 0.35}
                    y={f.H - 6}
                    {...AXIS}
                    textAnchor="middle"
                  >{`'${String(yr.year).slice(2)}`}</text>
                ) : null}
              </g>
            );
          })}
        </svg>
      </div>
      <p className="cap">
        Percent (100 × log change); dot = gold&rsquo;s change for the year,
        faded bars are partial years · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}
