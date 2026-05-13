import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Row = TradeInsightsResponse["term_structure_table"][number];

const fmtMoney = (v: unknown) => (v == null ? "-" : `$${Number(v).toFixed(2)}`);
const fmtPercent = (v: unknown) =>
  v == null ? "-" : `${(Number(v) * 100).toFixed(2)}%`;

export function TermMovePanel({ rows }: { rows: Row[] }) {
  if (rows.length === 0) {
    return (
      <InsightPanel heading="TERM STRUCTURE / IMPLIED MOVE">
        <InsightStatusBanner text="No iv_term_snapshots for this run" severity="info" />
      </InsightPanel>
    );
  }

  return (
    <InsightPanel heading="TERM STRUCTURE / IMPLIED MOVE">
      <DataTable
        rows={rows as unknown as Record<string, unknown>[]}
        columns={[
          { key: "expiry", label: "Expiry" },
          { key: "dte", label: "DTE" },
          { key: "atm_straddle", label: "ATM Straddle", render: fmtMoney },
          { key: "implied_move_perc", label: "Move", render: fmtPercent },
          { key: "daily_implied_move_perc", label: "Daily", render: fmtPercent },
          { key: "read", label: "Read" },
        ]}
      />
    </InsightPanel>
  );
}
