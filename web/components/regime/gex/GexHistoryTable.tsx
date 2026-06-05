"use client";

import { useMemo, useState } from "react";
import type { GexHistoryEntry } from "@/lib/regime/useGex";
import { biasColor, biasLabel, fmtGex, fmtPrice } from "./format";

type GexSortCol =
  | "date"
  | "net_gex"
  | "net_dex"
  | "gex_flip"
  | "spot"
  | "atm_iv"
  | "vol_pc"
  | "bias";
type SortDir = "asc" | "desc";

function sortIndicator(
  col: GexSortCol,
  activeCol: GexSortCol | null,
  dir: SortDir,
): string {
  if (col !== activeCol) return "";
  return dir === "asc" ? " \u2191" : " \u2193";
}

export function GexHistoryTable({ history }: { history: GexHistoryEntry[] }) {
  // Default newest-first; the sibling chart consumes the same `history`
  // array ASC, so we sort here instead of flipping the API response.
  const [sortCol, setSortCol] = useState<GexSortCol | null>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expanded, setExpanded] = useState(false);

  function handleSort(col: GexSortCol) {
    if (sortCol === col) {
      if (sortDir === "desc") setSortDir("asc");
      else {
        setSortCol(null);
        setSortDir("desc");
      }
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  const sorted = useMemo(() => {
    if (!sortCol) return history;
    return [...history].sort((a, b) => {
      const av = sortCol === "date" ? a.date : (a[sortCol] ?? -Infinity);
      const bv = sortCol === "date" ? b.date : (b[sortCol] ?? -Infinity);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [history, sortCol, sortDir]);

  if (!history.length) return null;

  const cols: { key: GexSortCol; label: string; align: string }[] = [
    { key: "date", label: "Date", align: "left" },
    { key: "spot", label: "Spot", align: "right" },
    { key: "gex_flip", label: "GEX Flip", align: "right" },
    { key: "net_gex", label: "Net GEX", align: "right" },
    { key: "net_dex", label: "Net DEX", align: "right" },
    { key: "atm_iv", label: "IV 30D", align: "right" },
    { key: "vol_pc", label: "Vol P/C", align: "right" },
    { key: "bias", label: "Bias", align: "center" },
  ];

  return (
    <div className="gex-history-section">
      <button
        className="gex-history-toggle"
        onClick={() => setExpanded(!expanded)}
      >
        History ({history.length} sessions) {expanded ? "\u25B2" : "\u25BC"}
      </button>
      {expanded && (
        <div className="gex-history-table-wrap">
          <table className="gex-history-table">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th
                    key={c.key}
                    className={`text-${c.align}`}
                    onClick={() => handleSort(c.key)}
                    style={{ cursor: "pointer", userSelect: "none" }}
                  >
                    {c.label}
                    {sortIndicator(c.key, sortCol, sortDir)}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.date}>
                  <td>{row.date}</td>
                  <td className="text-right">{fmtPrice(row.spot)}</td>
                  <td className="text-right">{fmtPrice(row.gex_flip)}</td>
                  <td
                    className="text-right"
                    style={{
                      color:
                        row.net_gex >= 0
                          ? "var(--signal-core)"
                          : "var(--fault)",
                    }}
                  >
                    {fmtGex(row.net_gex)}
                  </td>
                  <td className="text-right">{fmtGex(row.net_dex)}</td>
                  <td className="text-right">
                    {row.atm_iv != null
                      ? `${(row.atm_iv * 100).toFixed(1)}%`
                      : "---"}
                  </td>
                  <td className="text-right">
                    {row.vol_pc != null ? row.vol_pc.toFixed(2) : "---"}
                  </td>
                  <td className="text-center">
                    <span
                      style={{
                        color: biasColor(row.bias || "NEUTRAL"),
                        fontWeight: 600,
                        fontSize: 10,
                      }}
                    >
                      {biasLabel(row.bias || "NEUTRAL")}
                    </span>
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
