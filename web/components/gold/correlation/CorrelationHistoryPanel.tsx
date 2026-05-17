import type { components } from "@/lib/types";

import { CorrelationLineChart } from "./CorrelationLineChart";

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
      />
    </div>
  );
}
