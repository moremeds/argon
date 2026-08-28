import type { components } from "@/lib/types";

import { MONO_LABEL } from "./BoardPanel";

export type MacroFactor = components["schemas"]["MacroFactorState"];

/**
 * A set of the state's factors, as the board's metric tables render them.
 *
 * Two formatting decisions are load-bearing and both are refusals.
 *
 * **The Δ column carries no unit.** `change_over_window` is published without one, and it
 * is NOT in the level's unit: `PCEPILFE` is an index in 2017=100 while its change is
 * +0.03 in percentage points of the year-on-year rate. The velocity block names that unit
 * for the one metric it covers; the factor rows do not carry it at all. So the number is
 * printed signed and bare rather than wearing a unit inferred from the column beside it.
 *
 * **Direction tone is a per-domain argument, never a global.** For inflation a FALLING
 * print is an improvement and the board colours it green, which is the opposite of what
 * green means on every asset chart in this repo. That inversion is only legitimate where
 * the domain justifies it, so it is opt-in: `fallingIsGood` is off unless a caller states
 * the case, and the caller that states it also prints the sentence explaining it.
 */
function fmtLevel(f: MacroFactor): string {
  const n = Number(f.value);
  if (!Number.isFinite(n)) return "—";
  if (f.unit.startsWith("percent")) return `${n.toFixed(2)}%`;
  return n.toFixed(Math.abs(n) >= 100 ? 2 : 3);
}

function fmtDelta(raw: string | null | undefined): string {
  const n = raw === null || raw === undefined ? NaN : Number(raw);
  if (!Number.isFinite(n)) return "—";
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}`;
}

function directionColor(
  direction: MacroFactor["direction"],
  fallingIsGood: boolean,
): string {
  if (direction === "FALLING")
    return fallingIsGood ? "var(--positive)" : "var(--negative)";
  if (direction === "RISING")
    return fallingIsGood ? "var(--negative)" : "var(--positive)";
  return "var(--text-muted)";
}

const CELL: React.CSSProperties = {
  padding: "5px 0",
  borderTop: "1px solid var(--border-dim)",
  fontSize: 12,
  color: "var(--text-secondary)",
};

const NUM: React.CSSProperties = {
  ...CELL,
  textAlign: "right",
  whiteSpace: "nowrap",
  fontFamily: "var(--font-mono), monospace",
  color: "var(--text-primary)",
};

export function FactorTable({
  factors,
  fallingIsGood = false,
  testId,
}: {
  factors: readonly MacroFactor[];
  fallingIsGood?: boolean;
  testId: string;
}) {
  if (factors.length === 0) {
    return (
      <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
        No factor of this kind is carried on the published state.
      </p>
    );
  }
  return (
    <div style={{ overflowX: "auto" }}>
      <table
        data-testid={testId}
        style={{ width: "100%", borderCollapse: "collapse", minWidth: 460 }}
      >
        <thead>
          <tr>
            {["metric", "level", "Δ window", "direction", "period"].map(
              (h, i) => (
                <th
                  key={h}
                  style={{
                    ...MONO_LABEL,
                    textAlign: i === 0 || i === 3 ? "left" : "right",
                    paddingBottom: 6,
                    whiteSpace: "nowrap",
                  }}
                >
                  {h}
                </th>
              ),
            )}
          </tr>
        </thead>
        <tbody>
          {factors.map((f) => (
            <tr key={`${f.name}-${f.series_id}`}>
              <td style={CELL}>
                <span
                  style={{
                    fontFamily: "var(--font-mono), monospace",
                    color: "var(--text-primary)",
                  }}
                >
                  {f.series_id}
                </span>
                <span style={{ color: "var(--text-muted)" }}>
                  {" "}
                  {f.unit.replace(/_/g, " ")}
                </span>
              </td>
              <td style={NUM}>{fmtLevel(f)}</td>
              <td style={NUM}>{fmtDelta(f.change_over_window)}</td>
              <td
                style={{
                  ...CELL,
                  ...MONO_LABEL,
                  color: directionColor(f.direction, fallingIsGood),
                }}
              >
                {f.direction}
              </td>
              <td style={{ ...NUM, color: "var(--text-secondary)" }}>
                {f.period_end} · {f.age_days}d
              </td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

/** The series a set of factors stood on, for a panel footer. */
export function seriesList(factors: readonly MacroFactor[]): string {
  return factors.map((f) => f.series_id).join(" · ");
}
