"use client";

import { linearScale, pathFromPoints, niceTicks } from "@/lib/svgChart";
import type { SectorCrowdingRow } from "@/lib/regime/useSectorCrowding";

const W = 520;
const H = 130;
const PAD = { top: 12, right: 44, bottom: 20, left: 8 };

const C = {
  etf: "var(--accent-vivid, #60a5fa)",
  bench: "var(--accent-vol, #a78bfa)",
  grid: "rgba(148,163,184,0.10)",
  zero: "var(--border-dim)",
  muted: "var(--text-muted)",
  warn: "var(--warning, #f59e0b)",
  neg: "var(--negative, #ef4444)",
};

/** Total-return panel: ETF vs benchmark, both rebased to 0% at window start. */
function ReturnPanel({
  row,
  benchmark,
}: {
  row: SectorCrowdingRow;
  benchmark: string;
}) {
  // `series` is optional in the generated contract (it defaults to [] server
  // side, so OpenAPI marks it not-required) -- hence the ?? []. And the length
  // guard is the same one FlowPanel has: build_sector_crowding never emits an
  // empty series today, but if it ever did, `last` below would be undefined
  // and the .toFixed() would take the whole tab down.
  const pts = row.series ?? [];
  if (!pts.length) return null;

  const values = pts.flatMap((p) => [p.etf_cum_return, p.bench_cum_return]);
  const lo = Math.min(0, ...values);
  const hi = Math.max(0, ...values);
  // linearScale takes two TUPLES -- (domain, range) -- not four scalars.
  const x = linearScale([0, pts.length - 1], [PAD.left, W - PAD.right]);
  const y = linearScale([lo, hi], [H - PAD.bottom, PAD.top]);

  const etfPath = pathFromPoints(
    pts.map((p, i) => [x(i), y(p.etf_cum_return)] as [number, number]),
  );
  const benchPath = pathFromPoints(
    pts.map((p, i) => [x(i), y(p.bench_cum_return)] as [number, number]),
  );
  const last = pts[pts.length - 1];

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      data-testid="sector-crowding-return-chart"
    >
      <title>{`${row.ticker} vs ${benchmark} total return, last 63 sessions`}</title>
      {niceTicks(lo, hi, 4).map((t) => (
        <g key={t}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            stroke={t === 0 ? C.zero : C.grid}
          />
          <text
            x={W - PAD.right + 4}
            y={y(t) + 3}
            fill={C.muted}
            fontSize={9}
            fontFamily="var(--font-mono)"
          >
            {t.toFixed(0)}%
          </text>
        </g>
      ))}
      <path d={benchPath} fill="none" stroke={C.bench} strokeWidth={1.25} />
      <path d={etfPath} fill="none" stroke={C.etf} strokeWidth={1.5} />
      <text x={PAD.left} y={10} fontSize={9} fontFamily="var(--font-mono)">
        <tspan fill={C.etf}>
          {row.ticker} {last.etf_cum_return.toFixed(1)}%
        </tspan>
        <tspan fill={C.bench}>
          {"   "}
          {benchmark} {last.bench_cum_return.toFixed(1)}%
        </tspan>
      </text>
    </svg>
  );
}

/** Flow/AUM bars with the tweet's 2% / 5% / 10% threshold lines. */
function FlowPanel({ row }: { row: SectorCrowdingRow }) {
  const pts = (row.series ?? []).filter((p) => p.flow_aum_pct != null);
  if (!pts.length) return null;

  const values = pts.map((p) => p.flow_aum_pct as number);
  const lo = Math.min(0, ...values);
  const hi = Math.max(10, ...values);
  const x = linearScale([0, pts.length - 1], [PAD.left, W - PAD.right]);
  const y = linearScale([lo, hi], [H - PAD.bottom, PAD.top]);
  const barW = Math.max(1, (W - PAD.right - PAD.left) / pts.length - 1);

  return (
    <svg
      width="100%"
      viewBox={`0 0 ${W} ${H}`}
      role="img"
      data-testid="sector-crowding-flow-chart"
    >
      <title>{`${row.ticker} one-month net flow as a percent of AUM`}</title>
      {[2, 5, 10].map((t) => (
        <g key={t}>
          <line
            x1={PAD.left}
            x2={W - PAD.right}
            y1={y(t)}
            y2={y(t)}
            stroke={t >= 10 ? C.neg : C.warn}
            strokeWidth={0.75}
            strokeDasharray="3 3"
          />
          <text
            x={W - PAD.right + 4}
            y={y(t) + 3}
            fill={C.muted}
            fontSize={9}
            fontFamily="var(--font-mono)"
          >
            {t}%
          </text>
        </g>
      ))}
      <line
        x1={PAD.left}
        x2={W - PAD.right}
        y1={y(0)}
        y2={y(0)}
        stroke={C.zero}
      />
      {pts.map((p, i) => {
        const v = p.flow_aum_pct as number;
        const top = Math.min(y(v), y(0));
        return (
          <rect
            key={p.obs_date}
            x={x(i) - barW / 2}
            y={top}
            width={barW}
            height={Math.abs(y(v) - y(0))}
            fill={v >= 0 ? C.etf : C.muted}
            opacity={0.85}
          />
        );
      })}
    </svg>
  );
}

export function SectorCrowdingCharts({
  row,
  benchmark,
}: {
  row: SectorCrowdingRow;
  benchmark: string;
}) {
  return (
    <div
      data-testid="sector-crowding-charts"
      style={{ display: "flex", flexDirection: "column", gap: 8, padding: 8 }}
    >
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        Total return 3M
      </div>
      <ReturnPanel row={row} benchmark={benchmark} />
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-muted)",
        }}
      >
        1M net flow / AUM
      </div>
      <FlowPanel row={row} />
    </div>
  );
}
