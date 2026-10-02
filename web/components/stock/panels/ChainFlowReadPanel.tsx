import type { TradeInsightsResponse } from "@/lib/api";
import { chainFlowRead } from "@/lib/snapshot/chainFlow";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Row = TradeInsightsResponse["flow_table"][number];

function Highlight({
  label,
  value,
  tone = "neutral",
}: {
  label: string;
  value: string;
  tone?: "neutral" | "warning" | "positive";
}) {
  const color =
    tone === "warning"
      ? "var(--warning)"
      : tone === "positive"
        ? "var(--positive)"
        : "var(--text-primary)";
  return (
    <div
      style={{
        border: "1px solid var(--border-dim)",
        borderRadius: 4,
        background: "var(--bg-base)",
        padding: "9px 10px",
        display: "grid",
        gap: 5,
      }}
    >
      <div
        style={{
          color: "var(--text-muted)",
          fontFamily: "var(--font-mono)",
          fontSize: 10,
          textTransform: "uppercase",
        }}
      >
        {label}
      </div>
      <div style={{ color, fontFamily: "var(--font-mono)", fontSize: 14 }}>
        {value}
      </div>
    </div>
  );
}

function DrillDown({ rows }: { rows: Row[] }) {
  return (
    <details
      style={{
        borderTop: "1px solid var(--border-dim)",
        paddingTop: 10,
      }}
    >
      <summary
        style={{
          cursor: "pointer",
          color: "var(--text-secondary)",
          fontFamily: "var(--font-mono)",
          fontSize: 11,
        }}
      >
        Show highlighted strike rows
      </summary>
      <div
        style={{
          marginTop: 10,
          maxHeight: 260,
          overflow: "auto",
          border: "1px solid var(--border-dim)",
          background: "var(--bg-base)",
        }}
      >
        <DataTable<Row>
          rows={rows}
          nowrap
          columns={[
            { key: "strike", label: "Strike" },
            { key: "call_volume", label: "Call vol" },
            { key: "call_open_interest", label: "Call OI" },
            { key: "put_volume", label: "Put vol" },
            { key: "put_open_interest", label: "Put OI" },
            { key: "call_put_volume_ratio", label: "C/P" },
            { key: "volume_oi_note", label: "Vol/OI note" },
            { key: "read", label: "Read" },
          ]}
        />
      </div>
    </details>
  );
}

export function ChainFlowReadPanel({ rows }: { rows: Row[] }) {
  if (rows.length === 0) {
    return (
      <InsightPanel heading="CHAIN / FLOW READ">
        <InsightStatusBanner
          text="No option chain rows for this run"
          severity="info"
        />
      </InsightPanel>
    );
  }

  const {
    tapeRatio,
    t1Count,
    strongest,
    highlightedRows,
    flowRead,
    activityRead,
    confirmationRead,
  } = chainFlowRead(rows);
  const highlightedCount = highlightedRows.length;

  return (
    <InsightPanel
      heading="CHAIN / FLOW HIGHLIGHTS"
      subheading={`${highlightedCount} highlighted strikes from ${rows.length} rows`}
    >
      <div
        style={{
          color: "var(--text-secondary)",
          fontSize: 13,
          lineHeight: 1.55,
          minHeight: 78,
        }}
      >
        {flowRead} {activityRead} {confirmationRead}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 10,
        }}
      >
        <Highlight
          label="Call / Put volume"
          value={
            tapeRatio == null
              ? "Put volume unavailable"
              : `${tapeRatio.toFixed(2)}x`
          }
          tone={tapeRatio != null && tapeRatio > 1 ? "positive" : "neutral"}
        />
        <Highlight
          label="Highest activity"
          value={strongest ? `${strongest.strike} strike` : "Unavailable"}
        />
        <Highlight
          label="Needs T+1 OI"
          value={`${t1Count} strike${t1Count === 1 ? "" : "s"}`}
          tone={t1Count > 0 ? "warning" : "neutral"}
        />
      </div>
      <DrillDown rows={highlightedRows} />
    </InsightPanel>
  );
}
