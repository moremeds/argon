import type { components } from "@/lib/types";
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { DataTable } from "../panels/DataTable";
import { fmtMoney, toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type FlowAlert = components["schemas"]["FlowAlert"];

export function FlowTab({ report }: { report: Report }) {
  const f = report.flow;
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
        Flow Snapshot
      </h3>
      <MetricGrid cols={3}>
        <Metric label="Alerts" value={f.flow_count} />
        <Metric label="Net Premium" value={fmtMoney(toNum(f.net_premium))} />
        <Metric label="Bull Premium" value={fmtMoney(toNum(f.bull_premium))} />
        <Metric label="Bear Premium" value={fmtMoney(toNum(f.bear_premium))} />
        <Metric
          label="Ask-side Premium"
          value={fmtMoney(toNum(f.ask_side_premium))}
        />
        <Metric
          label="Bid-side Premium"
          value={fmtMoney(toNum(f.bid_side_premium))}
        />
      </MetricGrid>

      {f.top_alerts.length > 0 && (
        <>
          <h3
            style={{
              marginTop: 24,
              fontFamily: "var(--font-mono)",
              fontSize: 10,
              color: "var(--text-secondary)",
              letterSpacing: 1,
              textTransform: "uppercase",
            }}
          >
            Top Alerts
          </h3>
          <DataTable<FlowAlert>
            rows={f.top_alerts}
            columns={[
              {
                key: "id",
                label: "ID",
                render: (v) => String(v).slice(0, 8),
              },
              { key: "type", label: "Type" },
              { key: "expiry", label: "Expiry" },
              {
                key: "strike",
                label: "Strike",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
              {
                key: "price",
                label: "Price",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
              { key: "total_size", label: "Size" },
              {
                key: "total_premium",
                label: "Premium",
                render: (v) => fmtMoney(toNum(v)),
              },
              { key: "volume_oi_ratio", label: "Vol/OI" },
              { key: "alert_rule", label: "Rule" },
            ]}
          />
        </>
      )}
    </div>
  );
}
