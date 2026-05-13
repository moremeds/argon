import type { components } from "@/lib/types";
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { DataTable } from "../panels/DataTable";
import { fmtMoney, fmtDecimal, toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type OiChangeRow = components["schemas"]["OiChangeRow"];

const sectionHeading: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  color: "var(--text-secondary)",
  letterSpacing: 1,
  textTransform: "uppercase",
};

export function TablesTab({ report }: { report: Report }) {
  return (
    <div>
      {report.oi_change_top.length > 0 && (
        <>
          <h3 style={sectionHeading}>OI Change — Top Movers</h3>
          <DataTable<OiChangeRow>
            rows={report.oi_change_top}
            columns={[
              { key: "option_symbol", label: "Symbol" },
              { key: "curr_oi", label: "Curr OI" },
              { key: "last_oi", label: "Prev OI" },
              { key: "oi_diff_plain", label: "Δ OI" },
              { key: "volume", label: "Volume" },
              {
                key: "avg_price",
                label: "Avg Price",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
              {
                key: "percentage_of_total",
                label: "% Total",
              },
            ]}
          />
        </>
      )}

      <h3 style={{ ...sectionHeading, marginTop: 24 }}>Dark Pool</h3>
      <MetricGrid cols={2}>
        <Metric label="Prints" value={report.dark_pool_print_count} />
        <Metric
          label="Notional"
          value={fmtMoney(toNum(report.dark_pool_notional))}
        />
      </MetricGrid>

      {report.short_data && (
        <>
          <h3 style={{ ...sectionHeading, marginTop: 24 }}>Short Data</h3>
          <MetricGrid cols={3}>
            <Metric
              label="Shares Available"
              value={fmtDecimal(
                toNum(report.short_data.short_shares_available),
                0,
              )}
            />
            <Metric
              label="Fee Rate"
              value={report.short_data.fee_rate ?? "—"}
            />
            <Metric
              label="Rebate Rate"
              value={report.short_data.rebate_rate ?? "—"}
            />
          </MetricGrid>
        </>
      )}
    </div>
  );
}
