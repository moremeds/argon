"use client";

import { BoardPanel, BoardRead } from "@/components/macro/domain/BoardPanel";
import { chartFrame, pathFromPoints } from "@/lib/svgChart";
import { useChartWidth } from "@/lib/useChartWidth";

import { AXIS, COLOR, yearTicks, type GoldFlows } from "./shared";

type FlowPoint = GoldFlows["china_reserves_t"][number];

function FlowLine({ points, label }: { points: FlowPoint[]; label: string }) {
  const [chartRef, w] = useChartWidth<SVGSVGElement>(300);
  const f = chartFrame(w, 150, { top: 8, right: 8, bottom: 18, left: 40 });
  const vs = points.map((p) => p.value);
  const lo = Math.min(...vs);
  const hi = Math.max(...vs);
  const pad = (hi - lo) * 0.08 || 1;
  const x = f.x([0, Math.max(1, points.length - 1)]);
  const y = f.y([lo - pad, hi + pad]);
  const ticks = yearTicks(points.map((p) => p.obs_date));
  const every = Math.ceil(ticks.length / 4);
  return (
    <svg {...f.svg} ref={chartRef} aria-label={label}>
      {[lo, hi].map((t) => (
        <text key={t} x={f.M.left - 4} y={y(t) + 3} {...AXIS} textAnchor="end">
          {Math.round(t).toLocaleString("en-US")}
        </text>
      ))}
      <path
        d={pathFromPoints(points.map((p, i) => [x(i), y(p.value)]))}
        fill="none"
        stroke={COLOR.gold}
        strokeWidth={1.5}
      />
      {ticks
        .filter((_, k) => k % every === 0)
        .map((t) => (
          <text key={t.label} x={x(t.i)} y={f.H - 4} {...AXIS}>
            {t.label}
          </text>
        ))}
    </svg>
  );
}

function FlowPanel({
  id,
  title,
  points,
  unit,
  digits,
  cadence,
  source,
}: {
  id: string;
  title: string;
  points: FlowPoint[];
  unit: string;
  digits: number;
  cadence: string;
  source: string;
}) {
  const last = points.at(-1);
  return (
    <BoardPanel
      id={id}
      title={title}
      questions={["Q5"]}
      basis="REAL"
      source={source}
    >
      {last && points.length > 1 ? (
        <>
          <div className="chart">
            <FlowLine points={points} label={title} />
          </div>
          <p className="cap">
            {cadence}, latest {last.value.toFixed(digits)} {unit} (
            {last.obs_date})
          </p>
        </>
      ) : (
        <p className="cap">No history stored for this series.</p>
      )}
    </BoardPanel>
  );
}

/**
 * Flows and holdings, as stored. Only series argon keeps a history of are drawn: SGE
 * withdrawals and the Shanghai premium have no ingest, so they have no panel here.
 */
export function GoldFlowPanels({ flows }: { flows: GoldFlows }) {
  return (
    <div className="grid g4" style={{ marginTop: 12 }}>
      <FlowPanel
        id="gold-flow-china"
        title="China central bank gold · tonnes"
        points={flows.china_reserves_t}
        unit="t"
        digits={1}
        cadence="Quarterly"
        source="/api/gold/flows · cb_gold_reserves_monthly (CHN, WGC)"
      />
      <FlowPanel
        id="gold-flow-cftc"
        title="CFTC managed-money net · % of OI"
        points={flows.cftc_mm_net_pct_oi}
        unit="%"
        digits={1}
        cadence="Weekly"
        source="/api/gold/flows · cot_gold_weekly (managed money net ÷ open interest)"
      />
      <FlowPanel
        id="gold-flow-lbma"
        title="London vault gold · tonnes"
        points={flows.lbma_vault_t}
        unit="t"
        digits={0}
        cadence="Monthly"
        source="/api/gold/flows · exchange_inventory_daily (LBMA vault)"
      />
      <BoardPanel
        id="gold-flow-read"
        title="How to read flows"
        questions={["Q5"]}
        basis="REFERENCE"
        sourceLabel="Note"
        source="desk reading rule"
      >
        <BoardRead>
          Descriptive only. A reported reserve change is not a purchase, and
          positioning follows the week&rsquo;s gold price, so it is not a cause.
        </BoardRead>
      </BoardPanel>
    </div>
  );
}
