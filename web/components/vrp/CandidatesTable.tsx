import type { components } from "@/lib/types";
import { fmtDecimal, toNum } from "@/lib/formatters";

type VrpCandidateRow = components["schemas"]["VrpCandidateRow"];

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

export function CandidatesTable({
  candidates,
}: {
  candidates: VrpCandidateRow[];
}) {
  if (candidates.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
        No iron-condor candidates today (no RICH single name in a SELLABLE
        sector).
      </p>
    );
  }
  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={{ ...TH, textAlign: "left" }}>Ticker</th>
          <th style={TH}>Spot</th>
          <th style={TH}>IV</th>
          <th style={TH}>VRP z</th>
          <th style={TH}>Long P</th>
          <th style={TH}>Short P</th>
          <th style={TH}>Short C</th>
          <th style={TH}>Long C</th>
          <th style={TH}>Credit</th>
          <th style={TH}>Max Loss</th>
          <th style={{ ...TH, textAlign: "left" }}>Sector / Verdict</th>
        </tr>
      </thead>
      <tbody>
        {candidates.map((c) => (
          <tr key={c.ticker}>
            <td style={{ ...TD, textAlign: "left", fontWeight: 700 }}>
              {c.ticker}
            </td>
            <td style={TD}>{fmtDecimal(toNum(c.spot), 2)}</td>
            <td style={TD}>{fmtDecimal(toNum(c.iv), 2)}</td>
            <td style={TD}>{fmtDecimal(toNum(c.vrp_z), 2)}</td>
            <td style={TD}>{fmtDecimal(toNum(c.long_put), 1)}</td>
            <td style={TD}>{fmtDecimal(toNum(c.short_put), 1)}</td>
            <td style={TD}>{fmtDecimal(toNum(c.short_call), 1)}</td>
            <td style={TD}>{fmtDecimal(toNum(c.long_call), 1)}</td>
            <td style={{ ...TD, color: "var(--positive)" }}>
              {fmtDecimal(toNum(c.entry_credit), 2)}
            </td>
            <td style={{ ...TD, color: "var(--negative)" }}>
              {fmtDecimal(toNum(c.max_loss), 2)}
            </td>
            <td style={{ ...TD, textAlign: "left" }}>
              {c.bucket_sector ?? "—"}{" "}
              <span style={{ color: "var(--text-muted)" }}>
                {c.bucket_verdict ?? ""}
              </span>
            </td>
          </tr>
        ))}
      </tbody>
    </table>
  );
}
