import type { components } from "@/lib/types";
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { fmtSigned, toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];

export function VrpTab({ report }: { report: Report }) {
  const v = report.vrp;
  return (
    <div>
      <h3
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          color: "var(--text-secondary)",
          letterSpacing: 1,
          textTransform: "uppercase",
        }}
      >
        Volatility Risk Premium
      </h3>
      <MetricGrid cols={2}>
        <Metric label="VRP (IV − RV)" value={fmtSigned(toNum(v.vrp), 4)} />
        <Metric label="Signal" value={v.signal} />
      </MetricGrid>
      {v.note && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            border: "1px solid var(--border-dim)",
            borderRadius: 4,
            background: "var(--bg-panel)",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
            color: "var(--text-secondary)",
            whiteSpace: "pre-wrap",
          }}
        >
          {v.note}
        </div>
      )}
    </div>
  );
}
