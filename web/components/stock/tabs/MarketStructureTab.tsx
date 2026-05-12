import type { components } from "@/lib/types";
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { DataTable } from "../panels/DataTable";
import { fmtDecimal, toNum } from "@/lib/formatters";

type Report = components["schemas"]["SingleStockReport"];
type MaxPainRow = components["schemas"]["MaxPainRow"];

const sectionHeading: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  color: "var(--text-secondary)",
  letterSpacing: 1,
  textTransform: "uppercase",
};

export function MarketStructureTab({ report }: { report: Report }) {
  const m = report.market_structure;
  return (
    <div>
      <h3 style={sectionHeading}>Gamma Exposure</h3>
      <MetricGrid cols={4}>
        <Metric label="Net GEX" value={fmtDecimal(toNum(m.net_gex), 0)} />
        <Metric
          label="Call GEX"
          value={fmtDecimal(toNum(m.total_call_gex), 0)}
        />
        <Metric label="Put GEX" value={fmtDecimal(toNum(m.total_put_gex), 0)} />
        <Metric
          label="Max Pain (nearest)"
          value={`$${fmtDecimal(toNum(m.max_pain), 2)}`}
        />
      </MetricGrid>

      <h3 style={{ ...sectionHeading, marginTop: 24 }}>Top OI Strikes</h3>
      <div
        style={{
          display: "flex",
          gap: 32,
          fontFamily: "var(--font-mono)",
          fontSize: 12,
        }}
      >
        <div>
          <div style={{ color: "var(--text-muted)" }}>Calls</div>
          {m.top_call_oi_strikes?.length
            ? m.top_call_oi_strikes.map((s) => <div key={s}>${s}</div>)
            : "—"}
        </div>
        <div>
          <div style={{ color: "var(--text-muted)" }}>Puts</div>
          {m.top_put_oi_strikes?.length
            ? m.top_put_oi_strikes.map((s) => <div key={s}>${s}</div>)
            : "—"}
        </div>
      </div>

      {report.max_pain_rows.length > 0 && (
        <>
          <h3 style={{ ...sectionHeading, marginTop: 24 }}>
            Max Pain by Expiry
          </h3>
          <DataTable<MaxPainRow>
            rows={report.max_pain_rows}
            columns={[
              { key: "expiry", label: "Expiry" },
              {
                key: "max_pain",
                label: "Max Pain",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
              {
                key: "close",
                label: "Close",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
              {
                key: "next_upper_strike",
                label: "Upper",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
              {
                key: "next_lower_strike",
                label: "Lower",
                render: (v) => (v != null ? `$${v}` : "—"),
              },
            ]}
          />
        </>
      )}
    </div>
  );
}
