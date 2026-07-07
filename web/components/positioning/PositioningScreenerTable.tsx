import Link from "next/link";
import type { components } from "@/lib/types";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";

type Row = components["schemas"]["PositioningScreenerRow"];

const th: React.CSSProperties = {
  textAlign: "right",
  padding: "6px 10px",
  fontSize: 10,
  letterSpacing: 1,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  fontWeight: 500,
  borderBottom: "1px solid var(--border-dim)",
  whiteSpace: "nowrap",
};

const td: React.CSSProperties = {
  textAlign: "right",
  padding: "6px 10px",
  fontSize: 12,
  color: "var(--text-secondary)",
  fontFamily: "var(--font-mono)",
  whiteSpace: "nowrap",
};

function squeezeColor(label: string): string {
  if (label === "HIGH") return "var(--negative)";
  if (label === "ELEVATED") return "var(--warning)";
  if (label === "LOW") return "var(--positive)";
  return "var(--text-muted)";
}

function tiltColor(tilt: string): string {
  if (tilt === "BUYING") return "var(--positive)";
  if (tilt === "SELLING") return "var(--negative)";
  return "var(--text-muted)";
}

function pctFromFraction(v: unknown, digits = 1): string {
  const n = toNum(v);
  return n == null ? "—" : `${fmtDecimal(n * 100, digits)}%`;
}

function pct(v: unknown, digits = 1): string {
  const n = toNum(v);
  return n == null ? "—" : `${fmtDecimal(n, digits)}%`;
}

function usd(v: unknown): string {
  const n = toNum(v);
  if (n == null) return "—";
  const abs = Math.abs(n);
  const sign = n < 0 ? "-" : "";
  if (abs >= 1e9) return `${sign}$${fmtDecimal(abs / 1e9, 2)}B`;
  if (abs >= 1e6) return `${sign}$${fmtDecimal(abs / 1e6, 1)}M`;
  if (abs >= 1e3) return `${sign}$${fmtDecimal(abs / 1e3, 0)}K`;
  return `${sign}$${fmtDecimal(abs, 0)}`;
}

export function PositioningScreenerTable({ rows }: { rows: Row[] }) {
  if (rows.length === 0) {
    return (
      <div style={{ color: "var(--text-muted)", fontSize: 13, padding: 24 }}>
        No positioning snapshots banked yet.
      </div>
    );
  }

  return (
    <div style={{ overflowX: "auto" }}>
      <table
        style={{ borderCollapse: "collapse", width: "100%", minWidth: 900 }}
        data-testid="positioning-screener-table"
      >
        <thead>
          <tr>
            <th style={{ ...th, textAlign: "left" }}>Ticker</th>
            <th style={th}>Squeeze</th>
            <th style={th}>Score</th>
            <th style={th}>SI %Float</th>
            <th style={th}>DTC</th>
            <th style={th}>Borrow Fee</th>
            <th style={th}>Insider Flow</th>
            <th style={th}>Impl. Upside</th>
            <th style={th}>Pre-ER +</th>
            <th style={th}>ER In</th>
          </tr>
        </thead>
        <tbody>
          {rows.map((r) => {
            const upside = toNum(r.analyst_implied_upside_pct);
            const baseRate = toNum(r.er_positive_base_rate);
            return (
              <tr key={r.ticker} style={{ borderBottom: "1px solid var(--border-dim)" }}>
                <td style={{ ...td, textAlign: "left" }}>
                  <Link
                    href={`/stock/${r.ticker}/market-structure`}
                    style={{ color: "var(--accent-bg)", textDecoration: "none" }}
                  >
                    {r.ticker}
                  </Link>
                </td>
                <td style={{ ...td, color: squeezeColor(r.squeeze_label), fontWeight: 600 }}>
                  {r.squeeze_label}
                </td>
                <td style={td}>{r.squeeze_score ?? "—"}</td>
                <td style={td}>{pctFromFraction(r.si_pct_float)}</td>
                <td style={td}>{fmtDecimal(toNum(r.si_days_to_cover), 1)}</td>
                <td style={td}>{pct(r.si_fee_rate)}</td>
                <td style={{ ...td, color: tiltColor(r.insider_tilt) }}>
                  {usd(r.insider_net_flow)}
                </td>
                <td
                  style={{
                    ...td,
                    color:
                      upside == null
                        ? "var(--text-muted)"
                        : upside >= 0
                          ? "var(--positive)"
                          : "var(--negative)",
                  }}
                >
                  {upside == null ? "—" : `${fmtSigned(upside, 1)}%`}
                </td>
                <td style={td}>
                  {baseRate == null ? "—" : `${fmtDecimal(baseRate * 100, 0)}%`}
                </td>
                <td style={td}>
                  {r.days_to_next_er == null ? "—" : `${r.days_to_next_er}d`}
                </td>
              </tr>
            );
          })}
        </tbody>
      </table>
    </div>
  );
}
