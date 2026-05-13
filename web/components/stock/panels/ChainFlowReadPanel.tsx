import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Row = TradeInsightsResponse["flow_table"][number];

const fmtRatio = (v: unknown) => (v == null ? "-" : `${Number(v).toFixed(2)}x`);
const n = (v: string | number | null | undefined) => (v == null ? 0 : Number(v));

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
        padding: 10,
        display: "grid",
        gap: 4,
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
      <div style={{ color, fontFamily: "var(--font-mono)", fontSize: 13 }}>
        {value}
      </div>
    </div>
  );
}

export function ChainFlowReadPanel({ rows }: { rows: Row[] }) {
  if (rows.length === 0) {
    return (
      <InsightPanel heading="CHAIN / FLOW READ">
        <InsightStatusBanner text="No option chain rows for this run" severity="info" />
      </InsightPanel>
    );
  }

  const totalCallVolume = rows.reduce((sum, row) => sum + n(row.call_volume), 0);
  const totalPutVolume = rows.reduce((sum, row) => sum + n(row.put_volume), 0);
  const tapeRatio = totalPutVolume > 0 ? totalCallVolume / totalPutVolume : null;
  const t1Count = rows.filter((row) => row.requires_t1_oi_confirmation).length;
  const strongest = [...rows].sort(
    (a, b) =>
      n(b.call_volume) +
      n(b.put_volume) +
      n(b.call_open_interest) +
      n(b.put_open_interest) -
      (n(a.call_volume) +
        n(a.put_volume) +
        n(a.call_open_interest) +
        n(a.put_open_interest)),
  )[0];
  const highlightedRows = [...rows]
    .sort((a, b) => {
      const bScore =
        n(b.call_volume) +
        n(b.put_volume) +
        (b.requires_t1_oi_confirmation ? 100000 : 0);
      const aScore =
        n(a.call_volume) +
        n(a.put_volume) +
        (a.requires_t1_oi_confirmation ? 100000 : 0);
      return bScore - aScore;
    })
    .slice(0, 8);

  return (
    <InsightPanel
      heading="CHAIN / FLOW HIGHLIGHTS"
      subheading={`Showing ${highlightedRows.length} highlighted strikes from ${rows.length} rows`}
    >
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 8,
        }}
      >
        <Highlight
          label="Call / Put volume"
          value={tapeRatio == null ? "Put volume unavailable" : `${tapeRatio.toFixed(2)}x`}
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
      <DataTable
        rows={highlightedRows as unknown as Record<string, unknown>[]}
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
