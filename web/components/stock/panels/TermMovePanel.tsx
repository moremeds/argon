import type { TradeInsightsResponse } from "@/lib/api";
import { DataTable } from "./DataTable";
import { InsightPanel, InsightStatusBanner } from "./InsightPanel";

type Row = TradeInsightsResponse["term_structure_table"][number];

const fmtPercent = (v: unknown) =>
  v == null ? "-" : `${(Number(v) * 100).toFixed(2)}%`;
const n = (v: string | number | null | undefined) => (v == null ? null : Number(v));

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
            { key: "atm_straddle", label: "ATM straddle" },
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
        <InsightStatusBanner text="No iv_term_snapshots for this run" severity="info" />
      </InsightPanel>
    );
  }

  const byExpiry = [...rows].sort((a, b) => {
    const aDte = a.dte ?? 9999;
    const bDte = b.dte ?? 9999;
    return aDte - bDte;
  });
  const front = byExpiry[0];
  const back = byExpiry.find((row) => row.expiry !== front.expiry) ?? null;
  const highestDaily = [...rows].sort(
    (a, b) => (n(b.daily_implied_move_perc) ?? -1) - (n(a.daily_implied_move_perc) ?? -1),
  )[0];
  const frontDaily = n(front.daily_implied_move_perc);
  const backDaily = back ? n(back.daily_implied_move_perc) : null;
  const curveRead =
    frontDaily != null && backDaily != null && frontDaily > backDaily
      ? "Front elevated"
      : frontDaily != null && backDaily != null && frontDaily < backDaily
        ? "Back elevated"
        : "Flat / unclear";
  const highlightedCount = Math.min(rows.length, 6);
  const highlightedRows = byExpiry.slice(0, highlightedCount);
  const frontMove = fmtPercent(front.implied_move_perc);
  const frontDailyText = frontDaily == null ? "-" : fmtPercent(frontDaily);
  const backDailyText = backDaily == null ? null : fmtPercent(backDaily);
  const termRead =
    curveRead === "Front elevated" && backDailyText
      ? `Front expiry (${front.expiry}, ${front.dte ?? "?"} DTE) implies ${frontMove} total, or ${frontDailyText} per day, above the next expiry at ${backDailyText} per day.`
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
