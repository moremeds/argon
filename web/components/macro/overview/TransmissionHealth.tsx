import type { ReplayVerdict } from "../replay";
import { instantUtc } from "../format";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "../types";
import { FRESHNESS_COLOR, MONO_LABEL, Panel } from "./Panel";

/**
 * Whether the chain is transmitting: did each of tab 00's five publishers answer, for
 * which instant, and which upstream answers did the downstream domains actually consume.
 *
 * This is the panel that makes tab 00 an ops read rather than a second scoreboard, and
 * every column is a field already on the wire:
 *
 *  - answered / request failed / never computed — §9 invariant 2's three states, decided
 *    the same way every other slot on this desk decides them;
 *  - "answers for" is `as_of`, the instant the stored answer answers for, and the ONLY
 *    clock the request bounds on these routes (`WHERE as_of <= %s`);
 *  - "computed" is `computed_at` / `assembled_at`, which is provenance and NOT that bound
 *    — `storage/macro_domain_state.py:216-219` states that a later recompute of the same
 *    instant is legitimate, so the two columns can differ by months without anything being
 *    wrong. Showing them as two columns is what keeps the second from being read as the
 *    first;
 *  - freshness and age are `freshness` / `age_hours`, the engine's own.
 *
 * The edge list underneath is `MacroDomainStateResponse.upstream[]` — the upstream ANSWERS
 * a state consumed, carried on the edge that references them (`models/macro.py:503-520`).
 * It is printed VERBATIM and checked against nothing: whether a cited upstream is the one
 * the chain holds is the assembler's verdict, published by `/api/macro/snapshot` and
 * rendered by the cross-domain panel above. Re-deciding it here from the edges would be a
 * second opinion computed in a browser, and the two would disagree the first time an
 * engine changed.
 */
export function TransmissionHealth({
  domains,
  snapshot,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
}) {
  return (
    <Panel
      id="transmission"
      title="Transmission health"
      lede="Did each of this tab's five publishers answer, and what did it answer for. Two clocks are shown apart on purpose: an answer's own instant is what the replay request bounds, while the moment it was computed is provenance and may legitimately be much later."
    >
      <div style={{ overflowX: "auto" }}>
        <table
          style={{
            width: "100%",
            minWidth: 720,
            borderCollapse: "collapse",
            fontSize: 12,
          }}
        >
          <thead>
            <tr>
              {["Publisher", "Answered", "Answers for", "Computed", "Freshness"].map(
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
            <HealthRow
              id="snapshot"
              label="Chain snapshot"
              answered={snapshot.value !== null}
              error={snapshot.error}
              verdict={snapshot.verdict}
              answersFor={snapshot.value?.as_of}
              computed={snapshot.value?.assembled_at}
              freshness={null}
              ageHours={null}
              neverComputed="No snapshot has been assembled for this instant — nothing has checked whether the four belong together."
            />
            {CAUSAL_ORDER.map((domain) => (
              <HealthRow
                key={domain}
                id={domain}
                label={DOMAIN_LABEL[domain]}
                answered={domains[domain].value !== null}
                error={domains[domain].error}
                verdict={domains[domain].verdict}
                answersFor={domains[domain].value?.as_of}
                computed={domains[domain].value?.computed_at}
                freshness={domains[domain].value?.freshness ?? null}
                ageHours={domains[domain].value?.age_hours ?? null}
                neverComputed="The engine has not run for this instant."
              />
            ))}
          </tbody>
        </table>
      </div>

      <UpstreamEdges domains={domains} />
    </Panel>
  );
}

/** The replay verdict as a short word for a table cell. `not_replaying` prints nothing —
 *  a live page has no instant to have answered for, and an empty cell says that better
 *  than the word "live" repeated five times. */
function verdictWord(verdict: ReplayVerdict): string | null {
  switch (verdict.kind) {
    case "not_replaying":
      return null;
    case "replaying":
      return "replayed";
    case "unanswered":
      return "none at that instant";
    case "request_failed":
      return "request failed";
    case "answered_after":
      return "wrong instant";
  }
}

function HealthRow({
  id,
  label,
  answered,
  error,
  verdict,
  answersFor,
  computed,
  freshness,
  ageHours,
  neverComputed,
}: {
  id: string;
  label: string;
  answered: boolean;
  error?: string;
  verdict: ReplayVerdict;
  answersFor?: string | null;
  computed?: string | null;
  freshness: string | null;
  ageHours: number | null;
  neverComputed: string;
}) {
  const cell: React.CSSProperties = {
    padding: "9px 12px 9px 0",
    borderBottom: "1px solid var(--border-dim)",
    color: "var(--text-secondary)",
    fontFamily: "var(--font-mono), monospace",
    verticalAlign: "baseline",
  };
  const word = verdictWord(verdict);
  // Three states, kept apart. `error` is about our API; `!answered` without one is about
  // the pipeline; and only the second is a statement about the desk's own history.
  const status = error ? "request failed" : answered ? "yes" : "never computed";
  const statusColor = error
    ? "var(--negative)"
    : answered
      ? "var(--positive)"
      : "var(--text-muted)";

  return (
    <>
      <tr data-testid={`macro-health-${id}`} data-answered={status}>
        <th
          scope="row"
          style={{ ...cell, ...MONO_LABEL, color: "var(--text-primary)", fontWeight: 400 }}
        >
          {label}
        </th>
        <td style={{ ...cell, color: statusColor }}>
          {status}
          {word ? (
            <span style={{ ...MONO_LABEL, marginLeft: 8 }}>· {word}</span>
          ) : null}
        </td>
        <td style={cell}>{answersFor ? instantUtc(answersFor) : "—"}</td>
        <td style={cell}>{computed ? instantUtc(computed) : "—"}</td>
        <td
          style={{
            ...cell,
            color: freshness
              ? (FRESHNESS_COLOR[freshness] ?? "var(--text-muted)")
              : "var(--text-muted)",
          }}
        >
          {freshness ? `${freshness} · ${Math.round(ageHours ?? 0)}h` : "—"}
        </td>
      </tr>
      {!answered ? (
        <tr>
          <td
            colSpan={5}
            style={{
              padding: "0 12px 9px 0",
              borderBottom: "1px solid var(--border-dim)",
              fontSize: 12,
              lineHeight: 1.5,
              color: error ? "var(--negative)" : "var(--text-muted)",
            }}
          >
            {error ?? neverComputed}
          </td>
        </tr>
      ) : null}
    </>
  );
}

function UpstreamEdges({
  domains,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
}) {
  const edges = CAUSAL_ORDER.flatMap((domain) =>
    (domains[domain].value?.upstream ?? []).map((edge) => ({ domain, edge })),
  );

  return (
    <div style={{ marginTop: 16 }} data-testid="macro-transmission-edges">
      <p style={{ ...MONO_LABEL, margin: 0 }}>Upstream answers consumed</p>
      {edges.length > 0 ? (
        <ul style={{ margin: "8px 0 0", padding: 0, listStyle: "none", display: "grid", gap: 4 }}>
          {edges.map(({ domain, edge }) => (
            <li
              key={`${domain}-${edge.upstream_state_id}-${edge.causal_role}`}
              style={{ fontSize: 12, color: "var(--text-secondary)" }}
            >
              <span style={{ ...MONO_LABEL, color: "var(--text-primary)" }}>
                {DOMAIN_LABEL[domain]}
              </span>{" "}
              consumed{" "}
              <span style={{ fontFamily: "var(--font-mono), monospace" }}>
                {edge.domain} #{edge.upstream_state_id}
              </span>{" "}
              as {edge.causal_role.replace(/_/g, " ")} — {edge.state} ({edge.direction}),
              answering for {instantUtc(edge.as_of)}, from {edge.engine_version}
            </li>
          ))}
        </ul>
      ) : (
        <p style={{ margin: "8px 0 0", fontSize: 12, color: "var(--text-muted)" }}>
          No domain that answered cited an upstream answer. Inflation and policy/rates
          stand on observations alone, so an empty list is their normal shape and not a
          broken edge (`models/macro.py:550-553`); only a transmission domain has any.
        </p>
      )}
    </div>
  );
}
