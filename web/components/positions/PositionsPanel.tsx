"use client";

import { Fragment, useState } from "react";
import { api } from "@/lib/api";
import { fmtDecimal, fmtSigned, toNum } from "@/lib/formatters";
import type { components } from "@/lib/types";
import { PnlChart } from "./PnlChart";

type PositionRow = components["schemas"]["VrpMacroPositionRow"];
type PositionDetail = components["schemas"]["VrpMacroPositionDetail"];

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

function pnlColor(v: number | null): string {
  if (v == null) return "var(--text-muted)";
  return v > 0 ? "var(--positive)" : v < 0 ? "var(--negative)" : "var(--text-muted)";
}

function StatusBadge({ status, dte }: { status: string; dte: number }) {
  const open = status === "open";
  return (
    <span
      style={{
        fontFamily: "var(--font-mono)",
        fontSize: 11,
        padding: "1px 6px",
        borderRadius: 3,
        border: `1px solid ${open ? "var(--positive)" : "var(--border)"}`,
        color: open ? "var(--positive)" : "var(--text-muted)",
      }}
    >
      {open ? `OPEN · ${dte}d` : "EXPIRED"}
    </span>
  );
}

export function PositionsPanel({ positions }: { positions: PositionRow[] }) {
  const [openId, setOpenId] = useState<number | null>(null);
  const [details, setDetails] = useState<Record<number, PositionDetail | "loading" | "error">>(
    {},
  );

  if (positions.length === 0) {
    return (
      <p style={{ color: "var(--text-muted)", fontSize: 13 }}>
        No captured VRP-macro positions yet. Cohorts appear here once the daily
        entry-capture births one.
      </p>
    );
  }

  async function toggle(entryId: number) {
    if (openId === entryId) {
      setOpenId(null);
      return;
    }
    setOpenId(entryId);
    if (details[entryId] === undefined) {
      setDetails((d) => ({ ...d, [entryId]: "loading" }));
      try {
        const detail = await api.positionDetail(entryId);
        setDetails((d) => ({ ...d, [entryId]: detail }));
      } catch {
        setDetails((d) => ({ ...d, [entryId]: "error" }));
      }
    }
  }

  return (
    <table style={{ width: "100%", borderCollapse: "collapse" }}>
      <thead>
        <tr>
          <th style={{ ...TH, textAlign: "left" }}>Cohort</th>
          <th style={{ ...TH, textAlign: "left" }}>Born</th>
          <th style={{ ...TH, textAlign: "left" }}>Status</th>
          <th style={TH}>Bracket</th>
          <th style={TH}>Credit</th>
          <th style={TH}>Value</th>
          <th style={TH}>Unrealized</th>
          <th style={TH}>RoR</th>
          <th style={TH}>Marks</th>
        </tr>
      </thead>
      <tbody>
        {positions.map((p) => {
          const pnl = toNum(p.unrealized_pnl);
          const ror = toNum(p.return_on_risk);
          const expanded = openId === p.entry_id;
          const detail = details[p.entry_id];
          return (
            <Fragment key={p.entry_id}>
              <tr
                onClick={() => toggle(p.entry_id)}
                style={{ cursor: "pointer" }}
              >
                <td style={{ ...TD, textAlign: "left", fontWeight: 700 }}>
                  {p.name}
                  <span
                    style={{
                      color: "var(--text-muted)",
                      fontWeight: 400,
                      marginLeft: 6,
                      fontSize: 11,
                    }}
                  >
                    #{p.entry_id} {p.origin}
                  </span>
                </td>
                <td style={{ ...TD, textAlign: "left" }}>{p.birth_date}</td>
                <td style={{ ...TD, textAlign: "left" }}>
                  <StatusBadge status={p.status} dte={p.dte} />
                </td>
                <td style={TD}>
                  {fmtDecimal(toNum(p.short_strike), 0)}/
                  {fmtDecimal(toNum(p.wing_strike), 0)}
                </td>
                <td style={TD}>{fmtDecimal(toNum(p.entry_credit), 2)}</td>
                <td style={TD}>{fmtDecimal(toNum(p.current_value), 2)}</td>
                <td style={{ ...TD, color: pnlColor(pnl) }}>
                  {fmtSigned(pnl, 2)}
                </td>
                <td style={{ ...TD, color: pnlColor(ror) }}>
                  {ror == null ? "—" : `${fmtSigned(ror * 100, 0)}%`}
                </td>
                <td style={TD}>{p.n_marks}</td>
              </tr>
              {expanded && (
                <tr>
                  <td colSpan={9} style={{ ...TD, textAlign: "left", padding: "10px 10px 18px" }}>
                    {detail === "loading" && (
                      <span style={{ color: "var(--text-muted)", fontSize: 12 }}>
                        Loading P&L curve…
                      </span>
                    )}
                    {detail === "error" && (
                      <span style={{ color: "var(--negative)", fontSize: 12 }}>
                        Failed to load P&L curve.
                      </span>
                    )}
                    {detail && detail !== "loading" && detail !== "error" && (
                      <PnlChart
                        pnl={detail.pnl_series.map((pt) => toNum(pt.unrealized_pnl))}
                      />
                    )}
                  </td>
                </tr>
              )}
            </Fragment>
          );
        })}
      </tbody>
    </table>
  );
}
