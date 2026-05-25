import { useState } from "react";

import type { VcgHistoryEntry } from "@/lib/regime/useVcg";
import { formatSignedNumber } from "../primitives/format";

type VcgSortCol =
  | "date"
  | "vcg"
  | "vcg_adj"
  | "residual"
  | "beta1"
  | "beta2"
  | "vix"
  | "vvix"
  | "credit";
type SortDir = "asc" | "desc";

function sortIndicator(
  col: VcgSortCol,
  activeCol: VcgSortCol | null,
  dir: SortDir,
): string {
  if (col !== activeCol) return "";
  return dir === "asc" ? " ↑" : " ↓";
}

function sortHistory(
  rows: VcgHistoryEntry[],
  col: VcgSortCol | null,
  dir: SortDir,
): VcgHistoryEntry[] {
  if (!col) return rows;
  return [...rows].sort((a, b) => {
    const av =
      col === "date"
        ? a.date
        : ((a[col] as number | null | undefined) ?? -Infinity);
    const bv =
      col === "date"
        ? b.date
        : ((b[col] as number | null | undefined) ?? -Infinity);
    if (av < bv) return dir === "asc" ? -1 : 1;
    if (av > bv) return dir === "asc" ? 1 : -1;
    return 0;
  });
}

export function VcgHistoryTable({
  history,
  creditProxy,
}: {
  history: VcgHistoryEntry[];
  creditProxy: string;
}) {
  const [sortCol, setSortCol] = useState<VcgSortCol | null>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(col: VcgSortCol) {
    if (sortCol === col) {
      if (sortDir === "desc") {
        setSortDir("asc");
      } else {
        setSortCol(null);
        setSortDir("desc");
      }
    } else {
      setSortCol(col);
      setSortDir("desc");
    }
  }

  return (
    <table data-testid="vcg-history-table">
      <thead>
        <tr>
          {(
            [
              ["date", "Date", false],
              ["vcg", "VCG", true],
              ["vcg_adj", "VCG Adj", true],
              ["residual", "Residual", true],
              ["beta1", "β₁ (VVIX)", true],
              ["beta2", "β₂ (VIX)", true],
              ["vix", "VIX", true],
              ["vvix", "VVIX", true],
              ["credit", creditProxy, true],
            ] as [VcgSortCol, string, boolean][]
          ).map(([col, label, isRight]) => (
            <th
              key={col}
              className={`${isRight ? "right" : ""} sortable-th`}
              onClick={() => handleSort(col)}
              style={{
                cursor: "pointer",
                userSelect: "none",
                whiteSpace: "nowrap",
              }}
            >
              {label}
              {sortIndicator(col, sortCol, sortDir)}
            </th>
          ))}
        </tr>
      </thead>
      <tbody>
        {sortHistory(history, sortCol, sortDir).map((h: VcgHistoryEntry) => (
          <tr key={h.date}>
            <td>{h.date}</td>
            <td
              className="right"
              style={{
                color:
                  (h.vcg ?? 0) > 2
                    ? "var(--fault, var(--negative))"
                    : (h.vcg ?? 0) < -2
                      ? "var(--warning)"
                      : "var(--text-primary)",
              }}
            >
              {formatSignedNumber(h.vcg)}
            </td>
            <td className="right">{formatSignedNumber(h.vcg_adj)}</td>
            <td className="right">
              {h.residual != null ? h.residual.toFixed(6) : "---"}
            </td>
            <td className="right">
              {h.beta1 != null ? h.beta1.toFixed(6) : "---"}
            </td>
            <td className="right">
              {h.beta2 != null ? h.beta2.toFixed(6) : "---"}
            </td>
            <td className="right">{h.vix.toFixed(2)}</td>
            <td className="right">{h.vvix.toFixed(2)}</td>
            <td className="right">{h.credit.toFixed(2)}</td>
          </tr>
        ))}
        {history.length === 0 && (
          <tr>
            <td colSpan={9} style={{ textAlign: "center", color: "var(--text-muted)" }}>
              No history data
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
