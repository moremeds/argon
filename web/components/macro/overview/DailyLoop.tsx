import { confidencePct } from "../format";
import type {
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "../types";
import { FRESHNESS_COLOR, MONO_LABEL, Panel } from "./Panel";

/**
 * The morning read: four answers, in the engine's own causal order, on one line each.
 *
 * EVERY VALUE HERE IS PUBLISHED. `state`, `direction`, `confidence`, `freshness`,
 * `age_hours` and `engine_version` are fields of `MacroDomainStateResponse`
 * (`models/macro.py:523-553`), the same response the full cards below this panel render
 * and the same one tabs 03-05 will render when P6 registers them. Nothing is averaged,
 * weighted, blended or scored, and there is deliberately no fifth row: a "macro regime"
 * summarising the four is the composite §1 of the plan forbids and `macroDesk.test.tsx`
 * tests for.
 *
 * ORDER IS `CAUSAL_ORDER`, not the tab strip's order. The two disagree and both are right:
 * `macro/snapshot.py:43` runs inflation -> policy_rates -> usd -> gold, while the tab bar
 * runs Fed first because a rate decision is the event an operator arrives for. This panel
 * is the chain, so it takes the chain's order. Adjacency here is the ENGINE's claim about
 * causality, recorded in the store; it is not this panel's claim, and no copy on it may
 * say that row N causes row N+1 beyond what the engine's own upstream edges assert.
 */
export function DailyLoop({
  domains,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
}) {
  return (
    <Panel
      id="daily-loop"
      title="Daily loop"
      lede="The four domain states in the engine's causal order — inflation, then policy and rates, then the dollar, then the gold gate. Each row is one publisher's own stored answer, replayed; the desk adds nothing to them and combines none of them."
    >
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            minWidth: 620,
            borderCollapse: "collapse",
            fontSize: 12,
          }}
        >
          <thead>
            <tr>
              {["Domain", "State", "Direction", "Confidence", "Freshness", "Engine"].map(
                (heading) => (
                  <th
                    key={heading}
                    scope="col"
                    style={{
                      ...MONO_LABEL,
                      textAlign: "left",
                      padding: "0 12px 6px 0",
                      borderBottom: "1px solid var(--border-dim)",
                      fontWeight: 400,
                    }}
                  >
                    {heading}
                  </th>
                ),
              )}
            </tr>
          </thead>
          <tbody>
            {CAUSAL_ORDER.map((domain) => (
              <LoopRow key={domain} domain={domain} slot={domains[domain]} />
            ))}
          </tbody>
        </table>
      </div>
    </Panel>
  );
}

function LoopRow({
  domain,
  slot,
}: {
  domain: MacroDomainKey;
  slot: MacroOverviewSlot<MacroDomainState>;
}) {
  const cell: React.CSSProperties = {
    padding: "9px 12px 9px 0",
    borderBottom: "1px solid var(--border-dim)",
    color: "var(--text-secondary)",
    verticalAlign: "baseline",
  };
  const s = slot.value;

  return (
    <tr data-testid={`macro-loop-${domain}`}>
      <th
        scope="row"
        style={{ ...cell, ...MONO_LABEL, color: "var(--text-primary)", fontWeight: 400 }}
      >
        {DOMAIN_LABEL[domain]}
      </th>
      {s ? (
        <>
          <td
            style={{
              ...cell,
              fontFamily: "var(--font-mono), monospace",
              fontSize: 14,
              color: "var(--text-primary)",
            }}
          >
            {s.state}
          </td>
          <td style={{ ...cell, fontFamily: "var(--font-mono), monospace" }}>
            {s.direction}
          </td>
          <td style={{ ...cell, fontFamily: "var(--font-mono), monospace" }}>
            {confidencePct(s.confidence)}
          </td>
          <td
            style={{
              ...cell,
              fontFamily: "var(--font-mono), monospace",
              color: FRESHNESS_COLOR[s.freshness] ?? "var(--text-muted)",
            }}
          >
            {s.freshness} · {Math.round(s.age_hours)}h
          </td>
          <td style={{ ...cell, fontFamily: "var(--font-mono), monospace" }}>
            {s.engine_version}
          </td>
        </>
      ) : (
        // Three states, never two. A request that failed is a fact about our API; a domain
        // nobody has computed is a fact about the pipeline; and only one of them means
        // going to look at the scheduler.
        <td
          colSpan={5}
          style={{ ...cell, color: slot.error ? "var(--negative)" : "var(--text-muted)" }}
        >
          {slot.error ??
            "No state has been computed for this domain at this instant — the engine has not run, which is not the same as the request failing."}
        </td>
      )}
    </tr>
  );
}
