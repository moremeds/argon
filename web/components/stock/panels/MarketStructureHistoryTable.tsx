"use client";
import { useState } from "react";
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type HistoryRow = components["schemas"]["StockHistoryRow"];

const biasColors: Record<string, string> = {
  BULL: "var(--positive)",
  BEAR: "var(--negative)",
  CAUTIOUS_BULL: "var(--warning)",
  CAUTIOUS_BEAR: "var(--warning)",
  NEUTRAL: "var(--text-muted)",
};

function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

function fmtMoney(v: number | null): string {
  if (v == null) return "—";
  const abs = Math.abs(v);
  const sign = v >= 0 ? "+" : "-";
  if (abs >= 1e6)
    return `${sign}$${(abs / 1e6).toLocaleString("en-US", { maximumFractionDigits: 1 })}M`;
  if (abs >= 1e3)
    return `${sign}$${(abs / 1e3).toLocaleString("en-US", { maximumFractionDigits: 1 })}K`;
  return `${sign}$${abs.toFixed(0)}`;
}

function fmtPct(v: number | null, digits = 1): string {
  if (v == null) return "—";
  return `${(v * 100).toFixed(digits)}%`;
}

const headerStyle: React.CSSProperties = {
  fontSize: 10,
  letterSpacing: 1.5,
  textTransform: "uppercase",
  color: "var(--text-muted)",
  textAlign: "left",
  fontWeight: 400,
  padding: "8px 12px",
  borderBottom: "1px solid var(--border-dim)",
};

const cellStyle: React.CSSProperties = {
  padding: "8px 12px",
  fontFamily: "var(--font-mono)",
  fontSize: 12,
  color: "var(--text-primary)",
  borderBottom: "1px solid var(--border-dim)",
};

export function MarketStructureHistoryTable({ rows }: { rows: HistoryRow[] }) {
  const [open, setOpen] = useState(false);

  return (
    <div style={{ fontFamily: "var(--font-mono)" }}>
      <button
        onClick={() => setOpen((v) => !v)}
        style={{
          background: "transparent",
          color: "var(--text-secondary)",
          border: "none",
          fontFamily: "var(--font-mono)",
          fontSize: 12,
          letterSpacing: 0.5,
          padding: "8px 0",
          cursor: "pointer",
        }}
      >
        History ({rows.length} sessions) {open ? "▲" : "▼"}
      </button>

      {open && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={headerStyle}>Date</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Spot</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>GEX Flip</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Net GEX</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Net DEX</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>IV 30D</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Vol P/C</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Bias</th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => {
                const netGex = toNum(r.net_gex);
                const netDex = toNum(r.net_dex);
                const iv = toNum(r.iv30d);
                const pcr = toNum(r.pcr_vol);
                return (
                  <tr key={r.market_date}>
                    <td style={cellStyle}>{r.market_date}</td>
                    <td style={{ ...cellStyle, textAlign: "right" }}>
                      {fmtNum(toNum(r.spot), 2)}
                    </td>
                    <td style={{ ...cellStyle, textAlign: "right" }}>
                      {fmtNum(toNum(r.gex_flip), 2)}
                    </td>
                    <td
                      style={{
                        ...cellStyle,
                        textAlign: "right",
                        color:
                          netGex == null
                            ? "var(--text-muted)"
                            : netGex >= 0
                              ? "var(--positive)"
                              : "var(--negative)",
                      }}
                    >
                      {fmtMoney(netGex)}
                    </td>
                    <td
                      style={{
                        ...cellStyle,
                        textAlign: "right",
                        color:
                          netDex == null
                            ? "var(--text-muted)"
                            : netDex >= 0
                              ? "var(--positive)"
                              : "var(--negative)",
                      }}
                    >
                      {fmtMoney(netDex)}
                    </td>
                    <td style={{ ...cellStyle, textAlign: "right" }}>
                      {fmtPct(iv, 1)}
                    </td>
                    <td style={{ ...cellStyle, textAlign: "right" }}>
                      {fmtNum(pcr, 2)}
                    </td>
                    <td
                      style={{
                        ...cellStyle,
                        textAlign: "right",
                        color: biasColors[r.bias] ?? biasColors.NEUTRAL,
                        fontWeight: 700,
                      }}
                    >
                      {r.bias.replace("_", " ")}
                    </td>
                  </tr>
                );
              })}
              {rows.length === 0 && (
                <tr>
                  <td
                    style={{ ...cellStyle, color: "var(--text-muted)" }}
                    colSpan={8}
                  >
                    No history yet — sessions accumulate from scan_runs.
                  </td>
                </tr>
              )}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
