import type {
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "../types";
import { MONO_LABEL, Panel } from "./Panel";

/**
 * Every contradiction rule that fired INSIDE a domain, gathered from the four states.
 *
 * The rows are `MacroDomainStateResponse.contradictions[]` (`models/macro.py:436-438`,
 * carried at `:545`), the same list `DomainStateCard` prints per card and `StateSection`
 * prints on tab 01. This panel only puts them in one place, because an operator scanning
 * for what broke overnight should not have to open four cards to find out that nothing
 * did.
 *
 * ### It is a list. It must never become a ranking
 *
 * There is no severity ordering here and there may not be one. The engine publishes a
 * `rule` and a `detail` and nothing else — no weight, no level, no score — so any ordering
 * beyond "the order they were produced in" would be invented at the browser. Plan §8 names
 * that specifically for the CHAIN reasons ("a second severity ordering invented on the
 * client is a composite wearing a list's clothes"), and the argument is identical one
 * level down: sorting these would tell the reader which contradiction matters most, which
 * is a judgement no engine on this desk made.
 *
 * So the order is: the engine's own causal order across domains, and within a domain the
 * order the engine emitted them. Both are the producer's, not ours.
 *
 * ### The count carries its own denominator
 *
 * "3 contradictions" is unreadable without knowing how many domains were asked: a quiet
 * feed because nothing fired and a quiet feed because three engines never ran look
 * identical, and only one of them is good news. So the summary line names both, and the
 * domains that could not contribute are listed rather than silently reducing the
 * denominator.
 */
export function ContradictionFeed({
  domains,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
}) {
  const answered = CAUSAL_ORDER.filter((domain) => domains[domain].value !== null);
  const silent = CAUSAL_ORDER.filter((domain) => domains[domain].value === null);
  const rows = answered.flatMap((domain) =>
    (domains[domain].value?.contradictions ?? []).map((item) => ({
      domain,
      ...item,
    })),
  );

  return (
    <Panel
      id="contradictions"
      title="Contradiction feed"
      lede="Rules that fired inside a single domain, gathered from all four states. Ordered by the engine's causal order and, within a domain, by the order the engine produced them — never re-ranked, because no engine on this desk publishes a severity to rank them by."
    >
      <p
        data-testid="macro-contradiction-count"
        style={{ ...MONO_LABEL, margin: 0 }}
      >
        {rows.length} contradiction{rows.length === 1 ? "" : "s"} from{" "}
        {answered.length} of {CAUSAL_ORDER.length} domains that answered
      </p>

      {rows.length > 0 ? (
        <ul style={{ margin: "12px 0 0", padding: 0, listStyle: "none", display: "grid", gap: 8 }}>
          {rows.map((row) => (
            <li
              key={`${row.domain}-${row.rule}-${row.detail}`}
              data-testid={`macro-contradiction-row-${row.domain}`}
              style={{
                borderLeft: "2px solid var(--warning)",
                padding: "4px 0 4px 10px",
                fontSize: 12,
                color: "var(--text-secondary)",
                lineHeight: 1.5,
              }}
            >
              <span style={{ ...MONO_LABEL, color: "var(--text-primary)" }}>
                {DOMAIN_LABEL[row.domain]}
              </span>{" "}
              <span style={MONO_LABEL}>{row.rule.replace(/_/g, " ")}</span>
              <br />
              {row.detail}
            </li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: "12px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
          {answered.length > 0
            ? "No contradiction rule fired inside any domain that answered. That is a statement about the rules that ran, not a claim that the macro picture is consistent."
            : "No domain answered, so no contradiction rule was evaluated. An empty feed here means nothing was asked, not that nothing fired."}
        </p>
      )}

      {silent.length > 0 ? (
        <p
          data-testid="macro-contradiction-unasked"
          style={{ margin: "10px 0 0", fontSize: 12, color: "var(--text-muted)" }}
        >
          Not represented above: {silent.map((d) => DOMAIN_LABEL[d]).join(", ")} —{" "}
          {silent.length === 1 ? "this domain" : "these domains"} contributed no rows
          because {silent.length === 1 ? "it has" : "they have"} no state to evaluate at
          this instant, not because {silent.length === 1 ? "it is" : "they are"}{" "}
          uncontradicted.
        </p>
      ) : null}
    </Panel>
  );
}
