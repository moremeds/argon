import type { TradeInsightsResponse } from "@/lib/api";
import { InsightPanel } from "./InsightPanel";

type Reconciliation = TradeInsightsResponse["source_reconciliation"];
type Row = Reconciliation["rows"][number];

function SourceRowCard({ row }: { row: Row }) {
  return (
    <div
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
  );
}

export function SourceReconciliationPanel({
  reconciliation,
}: {
  reconciliation: Reconciliation;
}) {
  const visibleRows = reconciliation.rows.slice(0, 3);
  const overflowRows = reconciliation.rows.slice(3);

  return (
    <InsightPanel heading="SOURCE RECONCILIATION">
      <div style={{ fontSize: 13, lineHeight: 1.55 }}>
        <div
          style={{
            color: "var(--text-primary)",
            fontWeight: 700,
            marginBottom: 6,
          }}
        >
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
          {visibleRows.map((row, index) => (
            <SourceRowCard
              key={`${row.source_pair}-${row.decision}-${index}`}
              row={row}
            />
          ))}
          {overflowRows.length > 0 && (
            <details
              style={{
                borderTop: "1px solid var(--border-dim)",
                paddingTop: 8,
              }}
            >
              <summary
                style={{ color: "var(--text-secondary)", cursor: "pointer" }}
              >
                Show {overflowRows.length} more source row
                {overflowRows.length === 1 ? "" : "s"}
              </summary>
              <div style={{ display: "grid", gap: 8, marginTop: 8 }}>
                {overflowRows.map((row, index) => (
                  <SourceRowCard
                    key={`${row.source_pair}-${row.decision}-${index + 3}`}
                    row={row}
                  />
                ))}
              </div>
            </details>
          )}
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
