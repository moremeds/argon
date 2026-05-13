import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Row = TradeInsightsResponse["flow_table"][number];

const fmtRatio = (v: unknown) => (v == null ? "-" : `${Number(v).toFixed(2)}x`);

export function ChainFlowReadPanel({ rows }: { rows: Row[] }) {
  if (rows.length === 0) {
    return (
      <InsightPanel heading="CHAIN / FLOW READ">
        <InsightStatusBanner text="No option chain rows for this run" severity="info" />
      </InsightPanel>
    );
  }

  return (
    <InsightPanel heading="CHAIN / FLOW READ">
      <DataTable
        rows={rows as unknown as Record<string, unknown>[]}
        columns={[
          { key: "strike", label: "Strike" },
          { key: "call_volume", label: "Call Vol" },
          { key: "call_open_interest", label: "Call OI" },
          { key: "put_volume", label: "Put Vol" },
          { key: "put_open_interest", label: "Put OI" },
          { key: "call_put_volume_ratio", label: "C/P", render: fmtRatio },
          { key: "volume_oi_note", label: "Vol/OI Note" },
          { key: "read", label: "Read" },
        ]}
      />
    </InsightPanel>
  );
}
