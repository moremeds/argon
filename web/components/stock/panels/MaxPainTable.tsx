"use client";
import { useState } from "react";
import type { components } from "@/lib/types";
import { toNum } from "@/lib/formatters";

type MaxPainRow = components["schemas"]["MaxPainRow"];

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

function fmtNum(v: number | null, digits = 2): string {
  if (v == null) return "—";
  return v.toLocaleString("en-US", {
    minimumFractionDigits: digits,
    maximumFractionDigits: digits,
  });
}

export function MaxPainTable({ rows }: { rows: MaxPainRow[] }) {
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
        Max Pain ({rows.length} expiries) {open ? "▲" : "▼"}
      </button>

      {open && (
        <div style={{ overflowX: "auto" }}>
          <table style={{ width: "100%", borderCollapse: "collapse" }}>
            <thead>
              <tr>
                <th style={headerStyle}>Expiry</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Max Pain</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Close</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>Open</th>
                <th style={{ ...headerStyle, textAlign: "right" }}>
                  Next Lower
                </th>
                <th style={{ ...headerStyle, textAlign: "right" }}>
                  Next Upper
                </th>
              </tr>
            </thead>
            <tbody>
              {rows.map((r) => (
                <tr key={r.expiry}>
                  <td style={cellStyle}>{r.expiry}</td>
                  <td style={{ ...cellStyle, textAlign: "right" }}>
                    {fmtNum(toNum(r.max_pain), 2)}
                  </td>
                  <td style={{ ...cellStyle, textAlign: "right" }}>
                    {fmtNum(toNum(r.close), 2)}
                  </td>
                  <td style={{ ...cellStyle, textAlign: "right" }}>
                    {fmtNum(toNum(r.open), 2)}
                  </td>
                  <td
                    style={{
                      ...cellStyle,
                      textAlign: "right",
                      color: "var(--text-muted)",
                    }}
                  >
                    {fmtNum(toNum(r.next_lower_strike), 2)}
                  </td>
                  <td
                    style={{
                      ...cellStyle,
                      textAlign: "right",
                      color: "var(--text-muted)",
                    }}
                  >
                    {fmtNum(toNum(r.next_upper_strike), 2)}
                  </td>
                </tr>
              ))}
              {rows.length === 0 && (
                <tr>
                  <td
                    style={{ ...cellStyle, color: "var(--text-muted)" }}
                    colSpan={6}
                  >
                    No max-pain rows in the latest scan.
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
