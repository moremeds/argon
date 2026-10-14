"use client";

import { useState } from "react";

import { BoardPanel } from "@/components/macro/domain/BoardPanel";
import { Zone } from "@/components/macro/overview/Zone";
import type { components } from "@/lib/types";
import { chartFrame, pathFromPoints } from "@/lib/svgChart";
import { useChartWidth } from "@/lib/useChartWidth";

import { SlopeHistory } from "./GoldFactorPanels";
import { Toggle, WINDOWS, type WindowId } from "./GoldFactorToggles";
import {
  AXIS,
  COLOR,
  RESEARCH_LABEL,
  SOURCE,
  complete,
  fmt,
  sumParts,
  type GoldFactor,
} from "./shared";

export type Dxy = components["schemas"]["DxyResponse"];
type DxyPoint = Dxy["points"][number];

const DXY_SOURCE = "/api/macro/dxy · dxy_synthetic_daily (6 IB FX pairs)";

/** The six legs, in ICE weight order. The percent is the leg's weight in the index. */
const CURRENCIES = [
  { key: "eurusd_part", label: "EUR 57.6%" },
  { key: "usdjpy_part", label: "JPY 13.6%" },
  { key: "gbpusd_part", label: "GBP 11.9%" },
  { key: "usdcad_part", label: "CAD 9.1%" },
  { key: "usdsek_part", label: "SEK 4.2%" },
  { key: "usdchf_part", label: "CHF 3.6%" },
] as const;

/** The base row and the rows after it for a window: the last 5 or 21 rows, or this year
 *  measured from last year's final close. `null` when there is no base row. */
function windowOf(
  points: DxyPoint[],
  win: WindowId,
): { base: DxyPoint; rows: DxyPoint[] } | null {
  const w = WINDOWS.find((o) => o.id === win)!;
  const last = points.at(-1);
  if (!last) return null;
  const start = w.rows
    ? points.length - w.rows
    : points.findIndex((p) => p.obs_date.startsWith(last.obs_date.slice(0, 4)));
  if (start < 1) return null;
  return { base: points[start - 1], rows: points.slice(start) };
}

function pctChange(base: DxyPoint, last: DxyPoint): number {
  return (last.dxy / base.dxy - 1) * 100;
}

/** The index level over the last year, with its window moves as tiles. */
export function DxyPanel({ dxy }: { dxy: Dxy }) {
  const [chartRef, w] = useChartWidth<SVGSVGElement>(620);
  const pts = dxy.points.slice(-252);
  const last = pts.at(-1);
  const f = chartFrame(w, 150, { top: 8, right: 40, bottom: 18, left: 40 });
  const vs = pts.map((p) => p.dxy);
  const x = f.x([0, Math.max(1, pts.length - 1)]);
  const y = f.y([Math.min(...vs), Math.max(...vs)]);
  return (
    <BoardPanel
      id="usd-dxy"
      title="Dollar index (DXY)"
      questions={["Q1"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source={`${DXY_SOURCE} · ICE weights, 50.14348112 × Π pair^w`}
    >
      {last && pts.length > 1 ? (
        <>
          <div className="big num" data-testid="usd-dxy-now">
            {last.dxy.toFixed(2)} <small>{last.obs_date}</small>
          </div>
          <div className="chart">
            <svg {...f.svg} ref={chartRef} aria-label="Dollar index (DXY)">
              {[Math.min(...vs), Math.max(...vs)].map((t) => (
                <text
                  key={t}
                  x={f.M.left - 4}
                  y={y(t) + 3}
                  {...AXIS}
                  textAnchor="end"
                >
                  {t.toFixed(1)}
                </text>
              ))}
              <path
                d={pathFromPoints(pts.map((p, i) => [x(i), y(p.dxy)]))}
                fill="none"
                stroke={COLOR.dollar}
                strokeWidth={1.5}
              />
              <text x={f.M.left} y={f.H - 4} {...AXIS}>
                {pts[0].obs_date}
              </text>
            </svg>
          </div>
          <div className="grid g3" data-testid="usd-dxy-windows">
            {WINDOWS.map((w) => {
              const win = windowOf(dxy.points, w.id);
              return (
                <div key={w.id}>
                  <div className="cap">{w.text}</div>
                  <div className="num">
                    {win ? `${fmt(pctChange(win.base, last))}%` : "—"}
                  </div>
                </div>
              );
            })}
          </div>
          <p className="cap">
            Built from 6 IB FX pairs with ICE weights, one close per day.
          </p>
        </>
      ) : (
        <p className="cap">No dollar index stored yet.</p>
      )}
    </BoardPanel>
  );
}

/** Each currency's share of the window's move. The six parts add up to the index's log
 *  change exactly; the simple percent beside it differs only by the log-vs-simple gap. */
export function DxyPartsPanel({ dxy }: { dxy: Dxy }) {
  const [win, setWin] = useState<WindowId>("month");
  const [chartRef, W] = useChartWidth<SVGSVGElement>(440);
  const w = windowOf(dxy.points, win);
  const parts = CURRENCIES.map((c) => ({
    ...c,
    v: (w?.rows ?? []).reduce((a, p) => a + (p[c.key] ?? 0), 0),
  }));
  const total = parts.reduce((a, p) => a + p.v, 0);
  const m = Math.max(0.05, ...parts.map((p) => Math.abs(p.v))) * 1.3;
  const rh = 28;
  const L = 100;
  const R = 50;
  const x = (v: number) => L + ((v + m) / (2 * m)) * (W - L - R);
  return (
    <BoardPanel
      id="usd-dxy-parts"
      title="Move by currency"
      questions={["Q1"]}
      basis="COMPUTED"
      sourceLabel="Formula"
      source={`${DXY_SOURCE} · part = 100 × weight × Δlog(pair)`}
    >
      <Toggle label="Window" options={WINDOWS} value={win} onChange={setWin} />
      {w ? (
        <>
          <div className="chart">
            <svg
              ref={chartRef}
              viewBox={`0 0 ${W} ${parts.length * rh + 8}`}
              width="100%"
              style={{ maxWidth: 440 }}
              role="img"
              aria-label="Move by currency"
            >
              <line
                x1={x(0)}
                x2={x(0)}
                y1={0}
                y2={parts.length * rh + 4}
                stroke="var(--text-muted)"
              />
              {parts.map((p, i) => {
                const top = i * rh + 6;
                return (
                  <g key={p.key}>
                    <text
                      x={0}
                      y={top + 13}
                      {...AXIS}
                      fontSize={11}
                      fill="var(--text-secondary)"
                    >
                      {p.label}
                    </text>
                    <rect
                      x={Math.min(x(0), x(p.v))}
                      y={top + 3}
                      width={Math.max(1, Math.abs(x(p.v) - x(0)))}
                      height={rh - 12}
                      fill={COLOR.dollar}
                      rx={2}
                    />
                    <text
                      x={p.v >= 0 ? x(p.v) + 5 : x(p.v) - 5}
                      y={top + 13}
                      {...AXIS}
                      textAnchor={p.v >= 0 ? "start" : "end"}
                    >
                      {fmt(p.v)}
                    </text>
                  </g>
                );
              })}
            </svg>
          </div>
          <p className="cap" data-testid="usd-dxy-parts-cap">
            {w.base.obs_date} → {w.rows.at(-1)!.obs_date} · DXY{" "}
            {fmt(pctChange(w.base, w.rows.at(-1)!))}% · currencies sum to{" "}
            {fmt(total)} (100 × log change; the percent is the weight in DXY)
          </p>
        </>
      ) : (
        <p className="cap">Not enough data for this window.</p>
      )}
    </BoardPanel>
  );
}

/** Gold's dollar slope from the factor model, with its 95% interval. */
export function GoldDollarSensitivityPanel({ factor }: { factor: GoldFactor }) {
  const last = factor.points.filter((p) => p.b_d != null).at(-1);
  return (
    <BoardPanel
      id="usd-gold-sensitivity"
      title="Gold's sensitivity to the dollar"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      {last ? (
        <div className="big num">
          {fmt(last.b_d as number)}
          <small>
            {" "}
            %/% · 95% interval {fmt(last.b_d_lo95 as number)} to{" "}
            {fmt(last.b_d_hi95 as number)}
          </small>
        </div>
      ) : null}
      <div className="chart">
        <SlopeHistory
          pts={factor.points}
          k="b_d"
          label="Dollar · %/%"
          color={COLOR.dollar}
        />
      </div>
      <p className="cap">
        Gold&rsquo;s average move when the dollar rises 1% (past 252 trading
        days) · {RESEARCH_LABEL}
      </p>
    </BoardPanel>
  );
}

/** The last 21 trading days: gold's move, the dollar part inside it, and the rest. */
export function GoldDollarMonthPanel({ factor }: { factor: GoldFactor }) {
  const rows = complete(factor.points).slice(-21);
  const s = sumParts(rows);
  const bars = [
    { label: "Gold", v: s.gold_change, color: COLOR.gold },
    { label: "Dollar part", v: s.dollar_part, color: COLOR.dollar },
    {
      label: "Everything else",
      v: s.gold_change - s.dollar_part,
      color: COLOR.drift,
    },
  ];
  const [chartRef, w] = useChartWidth<SVGSVGElement>(300);
  const f = chartFrame(w, 170, { top: 16, right: 6, bottom: 22, left: 34 });
  const vals = bars.map((b) => b.v);
  const y = f.y([
    Math.min(0, ...vals) * 1.15,
    Math.max(0, ...vals) * 1.15 || 1,
  ]);
  const bw = (f.W - f.M.left - f.M.right) / bars.length;
  return (
    <BoardPanel
      id="usd-gold-month"
      title="This month: gold and its dollar part"
      questions={["Q4"]}
      basis="REAL"
      source={SOURCE}
    >
      {rows.length ? (
        <>
          <div className="chart">
            <svg
              {...f.svg}
              ref={chartRef}
              style={{ maxWidth: 420 }}
              aria-label="This month: gold and its dollar part"
            >
              <line
                x1={f.M.left}
                x2={f.W - f.M.right}
                y1={y(0)}
                y2={y(0)}
                stroke="var(--text-muted)"
              />
              {bars.map((b, i) => {
                const x0 = f.M.left + i * bw + bw * 0.2;
                const wd = bw * 0.6;
                return (
                  <g key={b.label}>
                    <rect
                      x={x0}
                      y={Math.min(y(0), y(b.v))}
                      width={wd}
                      height={Math.abs(y(b.v) - y(0))}
                      fill={b.color}
                      rx={2}
                    />
                    <text
                      x={x0 + wd / 2}
                      y={b.v < 0 ? y(b.v) + 13 : y(b.v) - 4}
                      {...AXIS}
                      textAnchor="middle"
                    >
                      {fmt(b.v, 1)}
                    </text>
                    <text
                      x={x0 + wd / 2}
                      y={f.H - 6}
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
            {rows[0].obs_date} → {rows.at(-1)!.obs_date} · 100 × log change ·{" "}
            {RESEARCH_LABEL}
          </p>
        </>
      ) : (
        <p className="cap">Not computed yet.</p>
      )}
    </BoardPanel>
  );
}

/** Tab 04's lead section (design v3): the index, its split by currency, and gold's
 *  relation to it. The Fed's weekly broad index stays below as reference. */
export function UsdDollarSection({
  dxy,
  factor,
}: {
  dxy: { value: Dxy | null; error?: string };
  factor: { value: GoldFactor | null; error?: string };
}) {
  return (
    <section className="board" data-testid="usd-dollar-section">
      <Zone
        first
        kicker="USD"
        label="Dollar index"
        testKey="usd-dxy"
        scope={dxy.value ? `through ${dxy.value.last_date}` : "updated nightly"}
      />
      {dxy.value ? (
        <div className="grid g2">
          <DxyPanel dxy={dxy.value} />
          <DxyPartsPanel dxy={dxy.value} />
        </div>
      ) : (
        <p className="cap">
          {dxy.error ??
            "Dollar index not computed yet (it runs nightly with the gold factor model)."}
        </p>
      )}
      {factor.value ? (
        <div className="grid g2" style={{ marginTop: 12 }}>
          <GoldDollarSensitivityPanel factor={factor.value} />
          <GoldDollarMonthPanel factor={factor.value} />
        </div>
      ) : factor.error ? (
        <p className="cap">{factor.error}</p>
      ) : null}
      <Zone
        kicker="Reference"
        label="Fed broad dollar index (weekly) · reference"
        testKey="usd-reference"
        scope="lags 4–8 days"
      />
    </section>
  );
}
