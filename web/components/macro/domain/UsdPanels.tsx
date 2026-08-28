import { BoardPanel, MONO_LABEL } from "./BoardPanel";
import type { MacroFactor } from "./FactorTable";
import type { MacroDomainState } from "../types";

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

/** Tab 04 — the two panels the board specifies for US Dollar. */
export function UsdPanels({ state }: { state: MacroDomainState }) {
  return (
    <div style={{ display: "grid", gap: 14 }}>
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
 * sentence is derived from the two signs at render time, never restated from the board.
 * Rendering "nominal falling, real rising" against data that says otherwise is exactly
 * the failure mode this whole port was corrected for.
 */
function DollarPairPanel({ state }: { state: MacroDomainState }) {
  const legs = resolveLegs(state);
  const notes = state.notes ?? [];
  const diverging =
    legs.length === 2 &&
    Math.sign(legs[0].change) !== Math.sign(legs[1].change);

  return (
    <BoardPanel
      id="dollar-pair"
      title="Nominal vs real · a dollar pair"
      questions={["Q1"]}
      basis="REAL"
      source={
        <>
          /api/macro/usd · factors[] for the levels, velocity[] for the changes
          — the velocity item is what carries the unit and the window, so the
          change is read from there.
        </>
      }
    >
      {legs.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
          Neither dollar leg is present on this state, so there is no pair to
          show.
        </p>
      ) : (
        <div
          data-testid="dollar-pair"
          style={{ display: "flex", gap: 28, flexWrap: "wrap" }}
        >
          {legs.map((leg) => (
            <div key={leg.factor.name} style={{ minWidth: 190 }}>
              <div
                style={{
                  fontFamily: "var(--font-mono), monospace",
                  fontSize: 26,
                  fontWeight: 700,
                  color: "var(--text-primary)",
                  lineHeight: 1.1,
                }}
              >
                {fmtIndex(leg.factor.value)}
              </div>
              <div style={{ ...MONO_LABEL, marginTop: 5 }}>{leg.label}</div>
              <div
                style={{
                  fontSize: 11,
                  color: "var(--text-secondary)",
                  marginTop: 3,
                  lineHeight: 1.5,
                }}
              >
                {leg.factor.series_id} · {leg.factor.period_end} ·{" "}
                {leg.factor.age_days}d
                <br />Δ{leg.windowMonths}m {fmtChange(leg.change)}
              </div>
            </div>
          ))}
        </div>
      )}

      {legs.length === 2 ? (
        <p
          data-testid="dollar-pair-read"
          style={{
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
          }}
        >
          {diverging ? (
            <>
              The two legs are moving in{" "}
              <strong style={{ color: "var(--text-primary)" }}>
                opposite directions
              </strong>{" "}
              over the same {legs[0].windowMonths}-month window. The gap between
              them is the US inflation differential against trading partners, so
              the read on export competitiveness is the opposite of what the
              nominal index alone would say.
            </>
          ) : (
            <>
              Both legs are moving in the{" "}
              <strong style={{ color: "var(--text-primary)" }}>
                same direction
              </strong>{" "}
              over the same {legs[0].windowMonths}-month window
              {Math.abs(legs[1].change - legs[0].change) >= 0.5 ? (
                <>
                  , the real index by{" "}
                  {Math.abs(legs[1].change - legs[0].change).toFixed(2)}pp more
                </>
              ) : null}
              . The inflation differential is not currently reversing the
              nominal read.
            </>
          )}
        </p>
      ) : null}

      {notes.length > 0 ? (
        <div style={{ display: "grid", gap: 4 }}>
          <div style={MONO_LABEL}>the engine&apos;s own rule for this pair</div>
          {notes.map((n) => (
            <p
              key={n}
              style={{
                margin: 0,
                fontSize: 12,
                lineHeight: 1.5,
                color: "var(--text-secondary)",
              }}
            >
              &ldquo;{n}&rdquo;
            </p>
          ))}
        </div>
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
 * shown as an identity — state row and inputs hash — not as a freshness stamp.
 */
function UpstreamCitationPanel({ state }: { state: MacroDomainState }) {
  const upstream = state.upstream ?? [];
  const factors = (state.factors ?? []) as MacroFactor[];

  return (
    <BoardPanel
      id="upstream-citation"
      title="Upstream citation · chain integrity"
      questions={["Q4", "Q7"]}
      basis="REAL"
      source="/api/macro/usd · upstream[] — the upstream's own state id, engine version and inputs hash, as this state recorded them"
    >
      {upstream.length === 0 ? (
        <p style={{ margin: 0, fontSize: 12, color: "var(--text-muted)" }}>
          This state cites no upstream domain.
        </p>
      ) : (
        <div style={{ overflowX: "auto" }}>
          <table
            data-testid="usd-upstream-table"
            style={{
              width: "100%",
              borderCollapse: "collapse",
              fontSize: 12,
              minWidth: 420,
            }}
          >
            <thead>
              <tr>
                {["upstream", "state", "citation identity"].map((h) => (
                  <th
                    key={h}
                    style={{
                      ...MONO_LABEL,
                      textAlign: "left",
                      paddingBottom: 6,
                    }}
                  >
                    {h}
                  </th>
                ))}
              </tr>
            </thead>
            <tbody>
              {upstream.map((u) => (
                <tr key={u.upstream_state_id}>
                  <td
                    style={{
                      padding: "5px 8px 5px 0",
                      borderTop: "1px solid var(--border-dim)",
                      color: "var(--text-secondary)",
                    }}
                  >
                    {u.domain}{" "}
                    <span style={{ color: "var(--text-muted)" }}>
                      as {u.causal_role.replace(/_/g, " ")}
                    </span>
                  </td>
                  <td
                    style={{
                      padding: "5px 8px 5px 0",
                      borderTop: "1px solid var(--border-dim)",
                      fontFamily: "var(--font-mono), monospace",
                      color: "var(--text-primary)",
                    }}
                  >
                    {u.state} · {u.direction}
                  </td>
                  <td
                    style={{
                      padding: "5px 0",
                      borderTop: "1px solid var(--border-dim)",
                      fontFamily: "var(--font-mono), monospace",
                      color: "var(--text-secondary)",
                      wordBreak: "break-all",
                    }}
                  >
                    state #{u.upstream_state_id} · {u.engine_version} · inputs{" "}
                    {u.inputs_hash.slice(0, 12)}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}

      <p
        style={{
          margin: 0,
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--text-secondary)",
        }}
      >
        The identity, not the value, is what is cited. If the rates engine
        recomputes while this state still names the hash above, the chain
        verdict on the overview reports the two as incompatible rather than
        quietly substituting the fresher answer.
      </p>

      <div
        style={{
          borderLeft: "2px solid var(--warning)",
          paddingLeft: 10,
          display: "grid",
          gap: 4,
        }}
      >
        <div style={MONO_LABEL}>honest boundary</div>
        <p
          style={{
            margin: 0,
            fontSize: 12,
            lineHeight: 1.5,
            color: "var(--text-secondary)",
          }}
        >
          This engine stands on {factors.length} published series (
          {factors.map((f) => f.series_id).join(", ") || "none"}) and one
          upstream state. Bilateral rates, CIP basis and foreign central-bank
          path differentials are not wired into it — so the state above is a
          reading of the broad dollar, and is not entitled to be read as a
          verdict on any specific pair.
        </p>
      </div>
    </BoardPanel>
  );
}
