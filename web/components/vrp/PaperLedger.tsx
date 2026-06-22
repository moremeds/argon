import type { components } from "@/lib/types";
import { fmtDecimal, toNum } from "@/lib/formatters";

type VrpPaperPositionRow = components["schemas"]["VrpPaperPositionRow"];

const TH: React.CSSProperties = {
  textAlign: "right",
  padding: "6px 10px",
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  fontFamily: "var(--font-mono)",
  borderBottom: "1px solid var(--border)",
};
const TD: React.CSSProperties = {
  textAlign: "right",
  padding: "6px 10px",
  fontFamily: "var(--font-mono)",
  fontSize: 13,
  borderBottom: "1px solid var(--border)",
};

function pnlStyle(v: number | null): React.CSSProperties {
  return {
    ...TD,
    color:
      v == null
        ? "var(--text-muted)"
        : v > 0
          ? "var(--positive)"
          : v < 0
            ? "var(--negative)"
            : "var(--text-muted)",
  };
}

export function PaperLedger({
  positions,
  totalRealizedPnl,
}: {
  positions: VrpPaperPositionRow[];
  totalRealizedPnl: string | null;
}) {
  if (positions.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
        No paper positions yet.
      </p>
    );
  }
  return (
    <div>
      <div
        style={{
          fontFamily: "var(--font-mono)",
          fontSize: 13,
          marginBottom: 8,
          color: "var(--text-muted)",
        }}
      >
        REALIZED P&L:{" "}
        <span
          style={{
            ...pnlStyle(toNum(totalRealizedPnl)),
            padding: 0,
            border: "none",
            fontSize: 16,
            fontWeight: 700,
          }}
        >
          {fmtDecimal(toNum(totalRealizedPnl), 0)}
        </span>
      </div>
      <table style={{ width: "100%", borderCollapse: "collapse" }}>
        <thead>
          <tr>
            <th style={{ ...TH, textAlign: "left" }}>Ticker</th>
            <th style={{ ...TH, textAlign: "left" }}>Opened</th>
            <th style={{ ...TH, textAlign: "left" }}>Status</th>
            <th style={TH}>Credit</th>
            <th style={TH}>Max Loss</th>
            <th style={TH}>Unrealized $</th>
            <th style={TH}>Realized $</th>
          </tr>
        </thead>
        <tbody>
          {positions.map((p) => (
            <tr key={p.position_id}>
              <td style={{ ...TD, textAlign: "left", fontWeight: 700 }}>
                {p.ticker}
              </td>
              <td style={{ ...TD, textAlign: "left" }}>{p.opened_on}</td>
              <td style={{ ...TD, textAlign: "left" }}>{p.status}</td>
              <td style={TD}>{fmtDecimal(toNum(p.entry_credit), 2)}</td>
              <td style={TD}>{fmtDecimal(toNum(p.max_loss), 2)}</td>
              <td style={pnlStyle(toNum(p.unrealized_pnl))}>
                {fmtDecimal(toNum(p.unrealized_pnl), 0)}
              </td>
              <td style={pnlStyle(toNum(p.realized_pnl))}>
                {fmtDecimal(toNum(p.realized_pnl), 0)}
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}
