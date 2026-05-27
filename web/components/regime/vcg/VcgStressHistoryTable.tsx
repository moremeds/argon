import { useState } from "react";

import type { components } from "@/lib/types";
import { formatSignedNumber } from "../primitives/format";

type VcgStressEntry = components["schemas"]["VcgStressHistoryEntry"];

type SortCol =
  | "date"
  | "interpretation"
  | "score"
  | "vcg_adj"
  | "pi_panic"
  | "vix"
  | "vvix"
  | "vix_percentile_rank"
  | "vvix_percentile_rank";
type SortDir = "asc" | "desc";

const VOL_STRESS_THRESHOLD = 0.95;

function interpretationColor(interp: VcgStressEntry["interpretation"]): string {
  switch (interp) {
    case "PANIC":
      return "var(--extreme, var(--negative))";
    case "RISK_OFF":
      return "var(--fault, var(--negative))";
    case "EDR":
      return "var(--warning)";
  }
}

function sortIndicator(
  col: SortCol,
  activeCol: SortCol | null,
  dir: SortDir,
): string {
  if (col !== activeCol) return "";
  return dir === "asc" ? " ↑" : " ↓";
}

function sortRows(
  rows: VcgStressEntry[],
  col: SortCol | null,
  dir: SortDir,
): VcgStressEntry[] {
  if (!col) return rows;
  return [...rows].sort((a, b) => {
    const av =
      col === "date" || col === "interpretation"
        ? (a[col] as string)
        : ((a[col] as number | null | undefined) ?? -Infinity);
    const bv =
      col === "date" || col === "interpretation"
        ? (b[col] as string)
        : ((b[col] as number | null | undefined) ?? -Infinity);
    if (av < bv) return dir === "asc" ? -1 : 1;
    if (av > bv) return dir === "asc" ? 1 : -1;
    return 0;
  });
}

function fmtPctRank(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "—";
  return `${(v * 100).toFixed(1)}%`;
}

function pctRankColor(v: number | null | undefined): string {
  if (v == null || !Number.isFinite(v)) return "var(--text-muted)";
  if (v >= VOL_STRESS_THRESHOLD) return "var(--fault, var(--negative))";
  if (v >= 0.85) return "var(--warning)";
  return "var(--text-primary)";
}

/**
 * All-time stress history table for the VCG v2 backtest.
 *
 * Renders every daily row in the latest production VCG run whose
 * interpretation is one of {PANIC, RISK_OFF, EDR}. Most-recent first by
 * default. The data source is /api/regime/vcg-validation → stress_history
 * (built from regime_backtest_daily, ~4,710 rows filtered to ~265 stress
 * entries).
 */
export function VcgStressHistoryTable({ rows }: { rows: VcgStressEntry[] }) {
  const [sortCol, setSortCol] = useState<SortCol | null>("date");
  const [sortDir, setSortDir] = useState<SortDir>("desc");

  function handleSort(col: SortCol) {
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

  const sorted = sortRows(rows, sortCol, sortDir);

  return (
    <table data-testid="vcg-stress-history-table">
      <thead>
        <tr>
          {(
            [
              ["date", "Date", false],
              ["interpretation", "Interp.", false],
              ["score", "Score", true],
              ["vcg_adj", "VCG Adj", true],
              ["pi_panic", "π Panic", true],
              ["vix", "VIX", true],
              ["vvix", "VVIX", true],
              ["vix_percentile_rank", "VIX %ile", true],
              ["vvix_percentile_rank", "VVIX %ile", true],
            ] as [SortCol, string, boolean][]
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
        {sorted.map((r) => {
          const override =
            r.vix_percentile_rank != null &&
            r.vvix_percentile_rank != null &&
            r.vix_percentile_rank >= VOL_STRESS_THRESHOLD &&
            r.vvix_percentile_rank >= VOL_STRESS_THRESHOLD;
          return (
            <tr
              key={r.date}
              data-testid={`vcg-stress-row-${r.date}`}
              data-interpretation={r.interpretation}
            >
              <td>{r.date}</td>
              <td>
                <span
                  className="pill"
                  style={{
                    background: interpretationColor(r.interpretation),
                    color: "#fff",
                    fontSize: "9px",
                    fontWeight: 700,
                    padding: "1px 6px",
                    borderRadius: "999px",
                  }}
                >
                  {r.interpretation === "RISK_OFF"
                    ? "RISK-OFF"
                    : r.interpretation}
                </span>
                {override && (
                  <span
                    style={{
                      marginLeft: "6px",
                      fontFamily: "var(--font-mono)",
                      fontSize: "9px",
                      color: "var(--fault, var(--negative))",
                      letterSpacing: "0.06em",
                    }}
                    title="VIX & VVIX percentile ranks both ≥ 0.95 — v2 absolute-vol-stress override"
                  >
                    V2-OVERRIDE
                  </span>
                )}
              </td>
              <td className="right">{formatSignedNumber(r.score)}</td>
              <td className="right">{formatSignedNumber(r.vcg_adj)}</td>
              <td className="right">
                {r.pi_panic != null ? r.pi_panic.toFixed(2) : "—"}
              </td>
              <td className="right">
                {r.vix != null ? r.vix.toFixed(2) : "—"}
              </td>
              <td className="right">
                {r.vvix != null ? r.vvix.toFixed(2) : "—"}
              </td>
              <td
                className="right"
                style={{ color: pctRankColor(r.vix_percentile_rank) }}
              >
                {fmtPctRank(r.vix_percentile_rank)}
              </td>
              <td
                className="right"
                style={{ color: pctRankColor(r.vvix_percentile_rank) }}
              >
                {fmtPctRank(r.vvix_percentile_rank)}
              </td>
            </tr>
          );
        })}
        {rows.length === 0 && (
          <tr>
            <td
              colSpan={9}
              style={{ textAlign: "center", color: "var(--text-muted)" }}
            >
              No stress-state days in the current backtest run.
            </td>
          </tr>
        )}
      </tbody>
    </table>
  );
}
