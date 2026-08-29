import { BoardRead, BoardRefusal } from "@/components/macro/domain/BoardPanel";

import { fmtValue, toFiniteNumber } from "../format";
import type { Policy } from "../types";

function fmtPolicyMetric(value: unknown, unit: string | undefined): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  if (unit === "$T") return `${n.toFixed(Math.abs(n) < 0.1 ? 3 : 2)} $T`;
  if (unit === "$bn") return `${n.toFixed(1)} $bn`;
  return fmtValue(value, unit, unit === "bps" ? 1 : 2);
}

/** The approved panel is one aggregate table, not three nested mini-panels. */
export function PolicySection({ policy }: { policy: Policy }) {
  const rows = policy.plumbing ?? [];
  return (
    <>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Aggregate</th>
              <th className="num">Level</th>
              <th>Qualifier (verbatim)</th>
            </tr>
          </thead>
          <tbody>
            {rows.map((row) => (
              <tr key={row.label}>
                <td>{row.label}</td>
                <td className="num">{fmtPolicyMetric(row.value, row.unit)}</td>
                <td>{row.qualifier ?? "—"}</td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <BoardRead>
        <b>{policy.target_range ?? "Target range unavailable"}</b>
        {policy.effr != null ? ` · EFFR ${fmtValue(policy.effr, "%", 2)}` : ""}
        {policy.sofr != null ? ` · SOFR ${fmtValue(policy.sofr, "%", 2)}` : ""}. {" "}
        {policy.plumbing_read ??
          policy.policy_read ??
          "Balance-sheet interpretation unavailable."}
      </BoardRead>
      {policy.status !== "ok" ? (
        <BoardRefusal kind="HONEST BOUNDARY">
          Plumbing status is {policy.status}; levels shown above remain publisher values,
          but they must not be read as equally fresh until the pipeline is complete.
        </BoardRefusal>
      ) : null}
    </>
  );
}
