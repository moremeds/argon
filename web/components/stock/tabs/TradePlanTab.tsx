import type { components } from "@/lib/types";
import { MetricGrid, Metric } from "../panels/MetricGrid";
import { DataTable } from "../panels/DataTable";

type Report = components["schemas"]["SingleStockReport"];
type Leg = components["schemas"]["TradePlanLeg"];

const sectionHeading: React.CSSProperties = {
  fontFamily: "var(--font-mono)",
  fontSize: 10,
  color: "var(--text-secondary)",
  letterSpacing: 1,
  textTransform: "uppercase",
};

export function TradePlanTab({ report }: { report: Report }) {
  if (!report.setup) {
    return (
      <div
        style={{
          color: "var(--text-muted)",
          fontSize: 12,
          fontFamily: "var(--font-mono)",
        }}
      >
        No Type C classification on this run.
      </div>
    );
  }

  const s = report.setup;
  return (
    <div>
      <h3 style={sectionHeading}>Setup</h3>
      <MetricGrid cols={4}>
        <Metric label="Type" value={s.setup_type} />
        <Metric label="Label" value={s.label} />
        <Metric label="Direction" value={s.direction} />
        <Metric label="Score" value={s.score} />
      </MetricGrid>

      {s.confirmations.length > 0 && (
        <>
          <h3 style={{ ...sectionHeading, marginTop: 24 }}>Confirmations</h3>
          <ul
            style={{
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text-primary)",
            }}
          >
            {s.confirmations.map((c, i) => (
              <li key={i}>{c}</li>
            ))}
          </ul>
        </>
      )}

      {s.warnings.length > 0 && (
        <div
          style={{
            marginTop: 16,
            padding: 12,
            border: "1px solid var(--warning)",
            borderRadius: 4,
            background: "var(--bg-panel)",
            fontFamily: "var(--font-mono)",
            fontSize: 12,
          }}
        >
          <div style={{ color: "var(--warning)", marginBottom: 4 }}>
            Warnings
          </div>
          {s.warnings.map((w, i) => (
            <div key={i}>{w}</div>
          ))}
        </div>
      )}

      {report.trade_plan && (
        <>
          <h3 style={{ ...sectionHeading, marginTop: 24 }}>Trade Plan</h3>
          <MetricGrid cols={4}>
            <Metric label="Structure" value={report.trade_plan.structure} />
            <Metric label="Direction" value={report.trade_plan.direction} />
            <Metric
              label="Max Loss"
              value={report.trade_plan.max_loss ?? "—"}
            />
            <Metric
              label="Max Profit"
              value={report.trade_plan.max_profit ?? "—"}
            />
          </MetricGrid>
          <div
            style={{
              marginTop: 16,
              fontFamily: "var(--font-mono)",
              fontSize: 12,
              color: "var(--text-secondary)",
              whiteSpace: "pre-wrap",
            }}
          >
            {report.trade_plan.rationale}
          </div>
          {report.trade_plan.legs.length > 0 && (
            <div style={{ marginTop: 16 }}>
              <DataTable<Leg>
                rows={report.trade_plan.legs}
                columns={[
                  { key: "side", label: "Side" },
                  { key: "option_symbol", label: "Symbol" },
                  {
                    key: "strike",
                    label: "Strike",
                    render: (v) => (v != null ? `$${v}` : "—"),
                  },
                  { key: "expiry", label: "Expiry" },
                  {
                    key: "mid",
                    label: "Mid",
                    render: (v) => (v != null ? `$${v}` : "—"),
                  },
                ]}
              />
            </div>
          )}
        </>
      )}
    </div>
  );
}
