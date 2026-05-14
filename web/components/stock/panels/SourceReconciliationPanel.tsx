import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Reconciliation = TradeInsightsResponse["source_reconciliation"];

export function SourceReconciliationPanel({
  reconciliation,
}: {
  reconciliation: Reconciliation;
}) {
  return (
    <InsightPanel heading="SOURCE RECONCILIATION">
      <div style={{ fontSize: 13, lineHeight: 1.55 }}>
        <div style={{ color: "var(--text-primary)", fontWeight: 700, marginBottom: 6 }}>
          {reconciliation.headline}
        </div>
        <div style={{ color: "var(--text-secondary)" }}>
          {reconciliation.decision}
        </div>
      </div>
      {reconciliation.rows.length > 0 ? (
        <div
          style={{
            display: "grid",
            gap: 8,
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          {reconciliation.rows.slice(0, 3).map((row) => (
            <div
              key={`${row.source_pair}-${row.decision}`}
              style={{
                border: "1px solid var(--border-dim)",
                background: "var(--bg-base)",
                padding: "8px 10px",
                display: "grid",
                gap: 4,
              }}
            >
              <div style={{ color: "var(--text-primary)" }}>{row.source_pair}</div>
              <div style={{ color: "var(--text-secondary)" }}>
                Price {row.price_agreement}; IV {row.iv_agreement}; {row.decision}
              </div>
            </div>
          ))}
        </div>
      ) : (
        <div
          style={{
            color: "var(--text-muted)",
            fontFamily: "var(--font-mono)",
            fontSize: 11,
          }}
        >
          No source reconciliation rows available.
        </div>
      )}
    </InsightPanel>
  );
}
