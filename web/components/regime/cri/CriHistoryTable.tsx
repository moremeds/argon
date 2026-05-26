import { useMemo, useState } from "react";

import type { CriHistoryEntry } from "../CriHistoryChart";

type CriTableSortCol =
  | "date"
  | "vix"
  | "vvix"
  | "spy"
  | "cor1m"
  | "realized_vol"
  | "spx_vs_ma_pct"
  | "vix_5d_roc";
type SortDir = "asc" | "desc";

function sortIndicator(
  col: CriTableSortCol,
  active: CriTableSortCol | null,
  dir: SortDir,
): string {
  if (active !== col) return "";
  return dir === "asc" ? " ▲" : " ▼";
}

function fmtNum(v: number | null | undefined, dec = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(dec);
}

function fmtPctCell(v: number | null | undefined, dec = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${v >= 0 ? "+" : ""}${v.toFixed(dec)}%`;
}

export function CriHistoryTable({ history }: { history: CriHistoryEntry[] }) {
  const [sortCol, setSortCol] = useState<CriTableSortCol | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expanded, setExpanded] = useState(true);

  function onSort(col: CriTableSortCol) {
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
    if (!sortCol) return [...history].reverse();
    return [...history].sort((a, b) => {
      const av =
        sortCol === "date"
          ? a.date
          : ((a[sortCol] as number | null | undefined) ?? -Infinity);
      const bv =
        sortCol === "date"
          ? b.date
          : ((b[sortCol] as number | null | undefined) ?? -Infinity);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [history, sortCol, sortDir]);

  if (!history.length) return null;

  const cols: { key: CriTableSortCol; label: string; align: string }[] = [
    { key: "date", label: "Date", align: "left" },
    { key: "vix", label: "VIX", align: "right" },
    { key: "vvix", label: "VVIX", align: "right" },
    { key: "spy", label: "SPY", align: "right" },
    { key: "cor1m", label: "COR1M", align: "right" },
    { key: "realized_vol", label: "RVOL", align: "right" },
    { key: "spx_vs_ma_pct", label: "vs 100d MA", align: "right" },
    { key: "vix_5d_roc", label: "VIX 5d RoC", align: "right" },
  ];

  return (
    <div
      className="gex-history-section"
      data-testid="cri-history-table-section"
    >
      <button
        className="gex-history-toggle"
        onClick={() => setExpanded(!expanded)}
        data-testid="cri-history-table-toggle"
      >
        History ({history.length} sessions) {expanded ? "▲" : "▼"}
      </button>
      {expanded && (
        <div className="gex-history-table-wrap">
          <table className="gex-history-table" data-testid="cri-history-table">
            <thead>
              <tr>
                {cols.map((c) => (
                  <th
                    key={c.key}
                    className={`text-${c.align}`}
                    onClick={() => onSort(c.key)}
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
                  <td className="text-right">{fmtNum(row.vix, 2)}</td>
                  <td className="text-right">{fmtNum(row.vvix, 1)}</td>
                  <td className="text-right">
                    {row.spy != null ? `$${fmtNum(row.spy, 2)}` : "—"}
                  </td>
                  <td className="text-right">{fmtNum(row.cor1m, 2)}</td>
                  <td className="text-right">
                    {row.realized_vol != null
                      ? `${fmtNum(row.realized_vol, 1)}%`
                      : "—"}
                  </td>
                  <td
                    className="text-right"
                    style={{
                      color:
                        row.spx_vs_ma_pct == null
                          ? undefined
                          : row.spx_vs_ma_pct >= 0
                            ? "var(--positive)"
                            : "var(--negative)",
                    }}
                  >
                    {fmtPctCell(row.spx_vs_ma_pct, 2)}
                  </td>
                  <td
                    className="text-right"
                    style={{
                      color:
                        row.vix_5d_roc == null
                          ? undefined
                          : row.vix_5d_roc >= 0
                            ? "var(--negative)"
                            : "var(--positive)",
                    }}
                  >
                    {fmtPctCell(row.vix_5d_roc, 1)}
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
