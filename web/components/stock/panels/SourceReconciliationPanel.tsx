import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Reconciliation = TradeInsightsResponse["source_reconciliation"];

export function SourceReconciliationPanel({
  reconciliation,
}: {
  reconciliation: Reconciliation;
}) {
  return (
    <InsightPanel heading="SOURCE RECONCILIATION">
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <div style={{ color: "var(--text-primary)", marginBottom: 4 }}>
          {reconciliation.headline}
        </div>
        <div style={{ color: "var(--text-secondary)", marginBottom: 12 }}>
          {reconciliation.decision}
        </div>
      </div>
      {reconciliation.rows.length > 0 ? (
        <DataTable
          rows={reconciliation.rows as unknown as Record<string, unknown>[]}
          columns={[
            { key: "source_pair", label: "Source Pair" },
            { key: "price_agreement", label: "Price" },
            { key: "iv_agreement", label: "IV" },
            { key: "decision", label: "Decision" },
          ]}
        />
      ) : (
        <InsightStatusBanner text="No source reconciliation data" severity="info" />
      )}
    </InsightPanel>
  );
}
