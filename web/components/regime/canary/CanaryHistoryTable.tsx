"use client";

import { useMemo, useState } from "react";

import type { components } from "@/lib/types";

type CanaryHistoryRow = components["schemas"]["CanaryHistoryRow"];

type SortCol =
  | "data_date"
  | "score"
  | "tactical_score"
  | "structural_score"
  | "speed_score";
type SortDir = "asc" | "desc";

const STATE_LABEL: Record<CanaryHistoryRow["warning_state"], string> = {
  NONE: "—",
  CONFIRMED_CANARY_ACTIVE: "CCA",
  BUY_THE_DIP_ACTIVE: "BTD",
  BOTH_ACTIVE_AMBIGUOUS: "BOTH",
};

const STATE_COLOR: Record<CanaryHistoryRow["warning_state"], string> = {
  NONE: "var(--text-muted)",
  CONFIRMED_CANARY_ACTIVE: "var(--negative)",
  BUY_THE_DIP_ACTIVE: "var(--positive)",
  BOTH_ACTIVE_AMBIGUOUS: "var(--warning)",
};

const BAND_COLOR: Record<CanaryHistoryRow["band"], string> = {
  NONE: "var(--text-muted)",
  WATCH: "var(--warning)",
  BUY: "var(--positive)",
  STRONG_BUY: "var(--accent-vivid)",
};

function sortIndicator(
  col: SortCol,
  active: SortCol | null,
  dir: SortDir,
): string {
  if (active !== col) return "";
  return dir === "asc" ? " ▲" : " ▼";
}

function fmtNum(v: number | null | undefined, dec = 2): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return v.toFixed(dec);
}

export function CanaryHistoryTable({
  history,
}: {
  history: CanaryHistoryRow[];
}) {
  const [sortCol, setSortCol] = useState<SortCol | null>(null);
  const [sortDir, setSortDir] = useState<SortDir>("desc");
  const [expanded, setExpanded] = useState(true);

  function onSort(col: SortCol) {
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
    if (!sortCol) return [...history];
    return [...history].sort((a, b) => {
      const av: string | number =
        sortCol === "data_date" ? a.data_date : (a[sortCol] as number);
      const bv: string | number =
        sortCol === "data_date" ? b.data_date : (b[sortCol] as number);
      if (av < bv) return sortDir === "asc" ? -1 : 1;
      if (av > bv) return sortDir === "asc" ? 1 : -1;
      return 0;
    });
  }, [history, sortCol, sortDir]);

  if (!history.length) return null;

  const cols: { key: SortCol | "band" | "state"; label: string }[] = [
    { key: "data_date", label: "Date" },
    { key: "score", label: "Score" },
    { key: "band", label: "Band" },
    { key: "state", label: "State" },
    { key: "tactical_score", label: "Tactical /30" },
    { key: "structural_score", label: "Structural /50" },
    { key: "speed_score", label: "Speed /20" },
  ];

  return (
    <div
      className="gex-history-section"
      data-testid="canary-history-table-section"
    >
      <button
        className="gex-history-toggle"
        onClick={() => setExpanded(!expanded)}
        data-testid="canary-history-table-toggle"
      >
        History ({history.length} sessions) {expanded ? "▲" : "▼"}
      </button>
      {expanded && (
        <div className="gex-history-table-wrap">
          <table
            className="gex-history-table"
            data-testid="canary-history-table"
          >
            <thead>
              <tr>
                {cols.map((c) => {
                  const sortable = c.key !== "band" && c.key !== "state";
                  return (
                    <th
                      key={c.key}
                      className={
                        c.key === "data_date" ? "text-left" : "text-right"
                      }
                      onClick={
                        sortable ? () => onSort(c.key as SortCol) : undefined
                      }
                      style={{
                        cursor: sortable ? "pointer" : "default",
                        userSelect: "none",
                      }}
                    >
                      {c.label}
                      {sortable
                        ? sortIndicator(c.key as SortCol, sortCol, sortDir)
                        : ""}
                    </th>
                  );
                })}
              </tr>
            </thead>
            <tbody>
              {sorted.map((row) => (
                <tr key={row.data_date}>
                  <td>{row.data_date}</td>
                  <td className="text-right">{fmtNum(row.score, 2)}</td>
                  <td
                    className="text-right"
                    style={{ color: BAND_COLOR[row.band] }}
                  >
                    {row.band}
                  </td>
                  <td
                    className="text-right"
                    style={{ color: STATE_COLOR[row.warning_state] }}
                  >
                    {STATE_LABEL[row.warning_state]}
                  </td>
                  <td className="text-right">
                    {fmtNum(row.tactical_score, 2)}
                  </td>
                  <td className="text-right">
                    {fmtNum(row.structural_score, 2)}
                  </td>
                  <td className="text-right">{row.speed_score}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
