import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";
import { termMoveRead } from "@/lib/snapshot/termMove";

type Row = TradeInsightsResponse["term_structure_table"][number];

const fmtMoney = (v: unknown) => (v == null ? "-" : `$${Number(v).toFixed(2)}`);
const fmtPercent = (v: unknown) =>
  v == null ? "-" : `${(Number(v) * 100).toFixed(2)}%`;

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
        Show highlighted expiry rows
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
            { key: "expiry", label: "Expiry" },
            { key: "dte", label: "DTE" },
            {
              key: "atm_straddle",
              label: "ATM straddle",
              render: (value) => fmtMoney(value),
            },
            {
              key: "implied_move_perc",
              label: "Move",
              render: (value) => fmtPercent(value),
            },
            {
              key: "daily_implied_move_perc",
              label: "Daily",
              render: (value) => fmtPercent(value),
            },
            { key: "read", label: "Read" },
          ]}
        />
      </div>
    </details>
  );
}

export function TermMovePanel({ rows }: { rows: Row[] }) {
  if (rows.length === 0) {
    return (
      <InsightPanel heading="TERM STRUCTURE / IMPLIED MOVE">
        <InsightStatusBanner
          text="No iv_term_snapshots for this run"
          severity="info"
        />
      </InsightPanel>
    );
  }

  const {
    front,
    highestDaily,
    frontDaily,
    backDaily,
    curveRead,
    highlightedCount,
    highlightedRows,
  } = termMoveRead(rows);
  const frontMove = fmtPercent(front?.implied_move_perc);
  const frontDailyText = frontDaily == null ? "-" : fmtPercent(frontDaily);
  const backDailyText = backDaily == null ? null : fmtPercent(backDaily);
  const termRead =
    curveRead === "Front elevated" && backDailyText
      ? `Front expiry (${front?.expiry}, ${front?.dte ?? "?"} DTE) implies ${frontMove} total, or ${frontDailyText} per day, above the next expiry at ${backDailyText} per day.`
      : curveRead === "Back elevated" && backDailyText
        ? `Front expiry implies ${frontDailyText} per day, below the next expiry at ${backDailyText} per day, so term pressure is farther out.`
        : `Front expiry implies ${frontMove} total, or ${frontDailyText} per day. The curve does not show a clear front/back edge.`;

  return (
    <InsightPanel
      heading="TERM / MOVE HIGHLIGHTS"
      subheading={`${highlightedCount} expiries from ${rows.length} rows`}
    >
      <div
        style={{
          color: "var(--text-secondary)",
          fontSize: 13,
          lineHeight: 1.55,
          minHeight: 78,
        }}
      >
        {termRead}
      </div>
      <div
        style={{
          display: "grid",
          gridTemplateColumns: "repeat(3, minmax(0, 1fr))",
          gap: 10,
        }}
      >
        <Highlight
          label="Curve read"
          value={curveRead}
          tone={curveRead === "Front elevated" ? "warning" : "neutral"}
        />
        <Highlight
          label="Front daily move"
          value={frontDaily == null ? "-" : fmtPercent(frontDaily)}
        />
        <Highlight
          label="Highest daily"
          value={
            highestDaily
              ? `${highestDaily.expiry} ${fmtPercent(highestDaily.daily_implied_move_perc)}`
              : "-"
          }
        />
      </div>
      <DrillDown rows={highlightedRows} />
    </InsightPanel>
  );
}
