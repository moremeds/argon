import { WIDE_FRAME } from "@/components/macro/chartGeometry";
import type { components } from "@/lib/types";

import { CorrelationLineChart } from "./CorrelationLineChart";

// The viewBox is the type scale, not a drawing detail: everything inside scales by
// containerWidth / viewBoxWidth, TEXT INCLUDED. This chart kept its pre-desk 640-unit
// default while sitting in the ~1200px full-width panel, so it rendered at k=1.83 and
// magnified its own 11px labels to ~20px. Height preserves the chart's own 8:3 aspect
// rather than borrowing WIDE_FRAME's, so only the scale changes and not the shape.
const CHART_WIDTH = WIDE_FRAME.width;
const CHART_HEIGHT = Math.round((WIDE_FRAME.width * 240) / 640);

type History = components["schemas"]["GoldCorrelationHistory"];

export function CorrelationHistoryPanel({ history }: { history: History }) {
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
      <h2
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          letterSpacing: 1.8,
          textTransform: "uppercase",
          color: "var(--text-primary, #cfd2db)",
          margin: 0,
        }}
      >
        CORRELATION HISTORY · 252D ROLLING
      </h2>
      <CorrelationLineChart
        series={[
          {
            id: "gold_dfii10",
            label: "GOLD ↔ DFII10",
            color: "var(--positive, #05ad98)",
            points: history.gold_dfii10 ?? [],
          },
          {
            id: "gold_dxy",
            label: "GOLD ↔ DXY",
            color: "var(--warning, #f5a623)",
            points: history.gold_dxy ?? [],
          },
          {
            id: "gold_gpr",
            label: "GOLD ↔ GPR",
            color: "var(--info, #3a8fd6)",
            points: history.gold_gpr ?? [],
          },
        ]}
        pre2022Band={history.pre_2022_band}
        width={CHART_WIDTH}
        height={CHART_HEIGHT}
      />
    </div>
  );
}
