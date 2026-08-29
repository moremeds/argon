import { BoardPanel, BoardRead, BoardRefusal } from "./BoardPanel";
import type { MacroFactor } from "./FactorTable";
import type { MacroDomainState } from "../types";
import { humanizeIdentifier, seriesLabel } from "../presentation";

/**
 * The USD engine's own vocabulary for its two legs, named explicitly rather than
 * pattern-matched.
 *
 * The pairing between a factor and the velocity item that measures it is not mechanical —
 * `broad_dollar` is measured by `broad_dollar_change` but `broad_dollar_real` by
 * `real_dollar_change`. Guessing it from a shared prefix would be a rule that happens to
 * work on two rows, so the two rows are written down.
 *
 * The Δ is taken from VELOCITY and not from the factor's `change_over_window`, even
 * though they carry the same number today: the velocity item states its unit (`percent`)
 * and its window (3 months), and the factor field states neither. A percentage rendered
 * from a field that does not claim to be one is a fabricated unit.
 */
const LEGS = [
  {
    factor: "broad_dollar",
    velocity: "broad_dollar_change",
    label: "H.10 nominal broad USD",
  },
  {
    factor: "broad_dollar_real",
    velocity: "real_dollar_change",
    label: "real broad USD",
  },
] as const;

type Leg = {
  label: string;
  factor: MacroFactor;
  change: number;
  unit: string;
  windowMonths: number;
};

function resolveLegs(state: MacroDomainState): Leg[] {
  const factors = (state.factors ?? []) as MacroFactor[];
  const velocity = state.velocity ?? [];
  const out: Leg[] = [];
  for (const spec of LEGS) {
    const factor = factors.find((f) => f.name === spec.factor);
    const v = velocity.find((item) => item.metric === spec.velocity);
    const change =
      v?.value === null || v?.value === undefined ? NaN : Number(v.value);
    if (!factor || !Number.isFinite(change)) continue;
    out.push({
      label: spec.label,
      factor,
      change,
      unit: v?.unit ?? "",
      windowMonths: v?.window_months ?? 0,
    });
  }
  return out;
}

function fmtIndex(raw: string): string {
  const n = Number(raw);
  return Number.isFinite(n) ? n.toFixed(2) : "—";
}

function fmtChange(n: number): string {
  return `${n >= 0 ? "+" : "−"}${Math.abs(n).toFixed(2)}%`;
}

/** Tab 04 — the two panels the board specifies for US Dollar, side by side as it has them. */
export function UsdPanels({ state }: { state: MacroDomainState }) {
  return (
    <div className="grid g2">
      <DollarPairPanel state={state} />
      <UpstreamCitationPanel state={state} />
    </div>
  );
}

/**
 * Board t4 · "Nominal vs real · a dollar pair in reverse".
 *
 * The board's title states a RELATIONSHIP — the two indexes moving in opposite directions
 * — and its prose draws its whole reading from that. The relationship held on the day the
 * board was captured and does not hold today: both legs are currently positive. So the
 * title here stops at "a dollar pair" and the sentence is derived from the two signs at
 * render time, never restated from the board. Rendering "nominal falling, real rising"
 * against data that says otherwise is exactly the failure mode this port was corrected
 * for — the board binds its design and its questions, not its frozen readings.
 */
function DollarPairPanel({ state }: { state: MacroDomainState }) {
  const legs = resolveLegs(state);
  const diverging =
    legs.length === 2 &&
    Math.sign(legs[0].change) !== Math.sign(legs[1].change);

  return (
    <BoardPanel
      id="dollar-pair"
      title="Nominal vs real dollar"
      questions={["Q1"]}
      basis="COMPUTED"
      sourceLabel="Pipeline"
      source={
        <>
          /api/macro/usd factors[] for the levels, velocity[] for the changes —
          the velocity item is what carries the unit and the window, so the
          change is read from there
          {state.notes?.[0] ? <> · {state.notes[0]}</> : null}
        </>
      }
    >
      {legs.length === 0 ? (
        <BoardRead>
          Neither dollar leg is present on this state, so there is no pair to
          show.
        </BoardRead>
      ) : (
        <div className="grid g2" data-testid="dollar-pair">
          {legs.map((leg) => (
            <div key={leg.factor.name}>
              <div className="big num">
                {fmtIndex(leg.factor.value)}
                <small> {leg.label}</small>
              </div>
              <div
                className={`num ${leg.change >= 0 ? "delta-up" : "delta-dn"}`}
                style={{ fontSize: 14 }}
              >
                Δ{leg.windowMonths}m {fmtChange(leg.change)}
              </div>
              <div
                className="num"
                style={{ fontSize: 10.5, color: "var(--text-muted)" }}
              >
                {seriesLabel(leg.factor.series_id)} · {leg.factor.period_end} ·{" "}
                {leg.factor.age_days}d
              </div>
            </div>
          ))}
        </div>
      )}

      {legs.length === 2 ? (
        <BoardRead testId="dollar-pair-read">
          {diverging ? (
            <>
              The two legs are moving in <b>opposite directions</b> over the
              same {legs[0].windowMonths}-month window. The gap between them is
              the US inflation differential against trading partners, so the
              read on export competitiveness and EM dollar-debt stress is the
              opposite of what the nominal index alone would say.
            </>
          ) : (
            <>
              Both legs are moving in the <b>same direction</b> over the same{" "}
              {legs[0].windowMonths}-month window
              {Math.abs(legs[1].change - legs[0].change) >= 0.5 ? (
                <>
                  , the real index by{" "}
                  {Math.abs(legs[1].change - legs[0].change).toFixed(2)}pp more
                </>
              ) : null}
              . The inflation differential is not reversing the nominal move.
            </>
          )}
        </BoardRead>
      ) : null}
    </BoardPanel>
  );
}

/**
 * Board t4 · "Upstream citation · chain integrity".
 *
 * The USD engine consumes the rates domain's PUBLISHED STATE and raises if handed a raw
 * upstream observation. That is what makes the snapshot's incompatible detection mean
 * something: if rates recomputes overnight while USD still cites the old identity, the
 * chain reports "not the same world" instead of pretending coherence. So the citation is
 * shown as an identity — state row and inputs hash — not as a freshness stamp, which is
 * why the board's third column is headed "Citation mode" and not "as of".
 */
function UpstreamCitationPanel({ state }: { state: MacroDomainState }) {
  const upstream = state.upstream ?? [];
  const factors = (state.factors ?? []) as MacroFactor[];

  return (
    <BoardPanel
      id="upstream-citation"
      title="Rates citation"
      questions={["Q4", "Q7"]}
      basis="REAL"
      source="/api/macro/usd upstream[] — the upstream's own state id, engine version and inputs hash, as this state recorded them"
    >
      {upstream.length === 0 ? (
        <BoardRead>This state cites no upstream domain.</BoardRead>
      ) : (
        <div className="tbl-wrap">
          <table data-testid="usd-upstream-table">
            <thead>
              <tr>
                <th>Upstream</th>
                <th>State</th>
                <th>Citation</th>
              </tr>
            </thead>
            <tbody>
              {upstream.map((u) => (
                <tr key={u.upstream_state_id}>
                  <td>
                    {humanizeIdentifier(u.domain)}{" "}
                    <span style={{ color: "var(--text-muted)" }}>
                      as {humanizeIdentifier(u.causal_role)}
                    </span>
                  </td>
                  <td>
                    <span className="state neust">
                      {humanizeIdentifier(u.state)}
                    </span>{" "}
                    <span className="num" style={{ fontSize: 11 }}>
                      {humanizeIdentifier(u.direction)}
                    </span>
                  </td>
                  <td>Stored state reference</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <BoardRead>
        The stored identity is cited, not recomputed. Overview flags any
        mismatch with the current Rates state.
      </BoardRead>

      <BoardRefusal kind="HONEST BOUNDARY">
        This engine uses {factors.length} broad-dollar series (
        {factors.map((f) => seriesLabel(f.series_id)).join(", ") || "none"}) and
        one Rates state. It is not a verdict on any currency pair.
      </BoardRefusal>
    </BoardPanel>
  );
}
