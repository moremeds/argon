import type { components } from "@/lib/types";

export type MacroFactor = components["schemas"]["MacroFactorState"];

/**
 * A set of the state's factors, in the board's metric-table grammar:
 * `Metric | Level | Δ window | Direction | Period`, numerics right-aligned in tabular
 * mono, direction carrying the delta colour. Styling is `app/macro/board.css`.
 *
 * Two formatting decisions are load-bearing and both are refusals.
 *
 * **The Δ column carries no unit — and here the board is deliberately not followed.** The
 * board's mock prints `−0.28pp`, but that "pp" is a value in a frozen mock, not a field on
 * the response: `change_over_window` is published without a unit and is NOT in the level's
 * unit (`PCEPILFE` is an index in 2017=100 while its change is in percentage points of the
 * year-on-year rate). The velocity block names a unit for the one metric it covers; the
 * factor rows do not carry it at all. So the number is printed signed and bare rather than
 * wearing a unit copied off a mock. The board binds its DESIGN; it does not license a unit
 * the API never sent.
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

function deltaClass(
  direction: MacroFactor["direction"],
  fallingIsGood: boolean,
): string {
  if (direction === "FALLING") return fallingIsGood ? "delta-up" : "delta-dn";
  if (direction === "RISING") return fallingIsGood ? "delta-dn" : "delta-up";
  return "delta-flat";
}

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
      <p className="read">
        No factor of this kind is carried on the published state.
      </p>
    );
  }
  return (
    <div className="tbl-wrap">
      <table data-testid={testId}>
        <thead>
          <tr>
            <th>Metric</th>
            <th className="num">Level</th>
            <th className="num">Δ window</th>
            <th>Direction</th>
            <th className="num">Period</th>
          </tr>
        </thead>
        <tbody>
          {factors.map((f) => (
            <tr key={`${f.name}-${f.series_id}`}>
              <td>
                {f.series_id}
                {/* The unit sits on its own line rather than running on after the id.
                    In a half-width panel the two together wrap mid-phrase, which reads
                    as a ragged accident; stacked, the wrap is the layout. */}
                <small
                  style={{
                    display: "block",
                    fontSize: 10,
                    color: "var(--text-muted)",
                  }}
                >
                  {f.unit.replace(/_/g, " ")}
                </small>
              </td>
              <td className="num">{fmtLevel(f)}</td>
              <td className="num">{fmtDelta(f.change_over_window)}</td>
              <td>
                <span className={deltaClass(f.direction, fallingIsGood)}>
                  {f.direction}
                </span>
              </td>
              <td className="num">
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
