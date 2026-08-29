import { ConfidenceArithmetic } from "@/components/macro/ConfidenceArithmetic";
import { BoardRead } from "@/components/macro/domain/BoardPanel";

import { toFiniteNumber } from "../format";
import type { MacroStateSummary } from "../types";

function fmtConfidence(value: unknown): string {
  const n = toFiniteNumber(value, Number.NaN);
  return Number.isFinite(n) ? `${(n * 100).toFixed(0)}%` : "n/a";
}

function fmtVelocity(value: unknown, unit: string): string {
  const n = toFiniteNumber(value, Number.NaN);
  if (!Number.isFinite(n)) return "n/a";
  const sign = n > 0 ? "+" : n < 0 ? "−" : "";
  return `${sign}${Math.abs(n).toFixed(2)} ${unit}`;
}

export function StateSection({
  state,
  errorMessage,
}: {
  state: MacroStateSummary | null | undefined;
  errorMessage?: string;
}) {
  if (!state) {
    return (
      <div className="note-refuse" data-testid="rates-state-missing">
        <b>Not computed · HONEST BOUNDARY</b>{" "}
        {errorMessage ??
          "No policy/rates domain state has been stored for this instant; the legacy scorecard is not a substitute."}
      </div>
    );
  }

  const contradictions = state.contradictions ?? [];
  return (
    <div data-testid="rates-state-block">
      <ConfidenceArithmetic
        reasons={state.confidence_reasons ?? []}
        testId="rates-confidence-strip"
      />
      <BoardRead>
        State <b data-testid="rates-state-label">{state.state.replace(/_/g, " ")}</b>
        {" · "}direction{" "}
        <b data-testid="rates-state-direction">{state.direction}</b> is published
        deliberately; UNKNOWN is not NEUTRAL. Confidence is{" "}
        <b data-testid="rates-state-confidence">{fmtConfidence(state.confidence)}</b>
        {" · "}
        <span data-testid="rates-state-freshness">
          {state.freshness === "stale"
            ? `Stale · ${state.age_hours.toFixed(1)}h since computed`
            : "fresh"}
        </span>
        {` · engine ${state.engine_version}. Stood on ${state.evidence_count} observations.`}
      </BoardRead>
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Velocity metric</th>
              <th className="num">Value</th>
            </tr>
          </thead>
          <tbody>
            {(state.velocity ?? []).map((item) => (
              <tr key={item.metric}>
                <td>{item.metric}</td>
                <td className="num">
                  {item.unavailable_reason ?? fmtVelocity(item.value, item.unit)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      {contradictions.length ? (
        <div className="note-refuse" data-testid="rates-state-contradictions">
          <b>CONTRADICTIONS</b>
          <ul>
            {contradictions.map((item) => (
              <li key={`${item.rule}:${item.detail}`}>
                <strong>{item.rule}</strong> — {item.detail}
              </li>
            ))}
          </ul>
        </div>
      ) : null}
    </div>
  );
}
