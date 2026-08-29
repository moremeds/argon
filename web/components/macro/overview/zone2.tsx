import type { components } from "@/lib/types";

import { BoardPanel, BoardRead } from "../domain/BoardPanel";
import { instantUtc, plural } from "../format";
import { humanizeIdentifier, humanizeText } from "../presentation";
import type { ReplayVerdict } from "../replay";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL, STATUS_LEDE } from "../types";

/** Zone 2 keeps within-domain findings separate from assembler findings. */

type PolicyComparison = components["schemas"]["PolicyComparison"];
type PolicyLane = PolicyComparison["actual"];

/** The four lanes, in the board's order: what happened, what the committee projects, what
 *  dealers expect, what the market prices. Ordered by authority, not by recency. */
const LANES: readonly {
  key: keyof Pick<
    PolicyComparison,
    "actual" | "committee_projection" | "dealer_expectations" | "market_implied"
  >;
  label: string;
}[] = [
  { key: "actual", label: "Actual" },
  { key: "committee_projection", label: "Fed projections" },
  { key: "dealer_expectations", label: "Dealer survey" },
  { key: "market_implied", label: "Market pricing" },
];

/** The nearest published rate, or null without blanking the other lanes. */
function nearestRate(lane: PolicyLane | undefined): {
  rate: number;
  horizon: string;
  horizonDate: string | null;
} | null {
  const points = lane?.path?.points ?? [];
  const dated = points
    .map((p) => ({
      rate: Number(p.rate_percent),
      horizon: p.horizon,
      horizonDate: p.horizon_date ?? null,
    }))
    .filter((p) => Number.isFinite(p.rate));
  if (dated.length === 0) return null;
  // The nearest horizon is the first dated point; an undated lane keeps producer order.
  const sorted = [...dated].sort((a, b) =>
    a.horizonDate && b.horizonDate
      ? a.horizonDate.localeCompare(b.horizonDate)
      : 0,
  );
  return sorted[0];
}

/** Four rows stay visible even when one publisher declines to provide a path. */
export function PolicyPathsPanel({
  policy,
}: {
  policy: { value: PolicyComparison | null; error?: string };
}) {
  const p = policy.value;
  const rows = LANES.map((lane) => ({
    ...lane,
    value: p?.[lane.key],
    nearest: nearestRate(p?.[lane.key]),
  }));
  const served = rows.filter((r) => r.nearest);
  const spread =
    served.length >= 2
      ? Math.max(...served.map((r) => r.nearest!.rate)) -
        Math.min(...served.map((r) => r.nearest!.rate))
      : null;

  return (
    <BoardPanel
      id="policy-paths"
      title="Policy paths"
      questions={["Q2", "Q3"]}
      basis="COMPUTED"
      sourceLabel="Pipeline"
      source={
        <>
          /api/macro/policy ← macro_observations (POLICY_PATH_* series) ·{" "}
          {p?.as_of
            ? `assembled for ${instantUtc(p.as_of)}`
            : "no comparison assembled"}
        </>
      }
    >
      {policy.error ? (
        <p className="cap" style={{ color: "var(--negative)" }}>
          {policy.error}
        </p>
      ) : !p ? (
        <p className="cap">
          No policy comparison has been assembled for this instant. That is the
          absence of a computation, not a failed request.
        </p>
      ) : (
        <>
          <div className="tbl-wrap">
            <table>
              <thead>
                <tr>
                  <th>Lane</th>
                  <th>Nearest horizon</th>
                  <th className="num">Rate %</th>
                </tr>
              </thead>
              <tbody>
                {rows.map((row) => (
                  <tr
                    key={row.key}
                    data-testid={`macro-policy-lane-${row.key}`}
                  >
                    <td>{row.label}</td>
                    {row.nearest ? (
                      <>
                        <td>
                          {row.nearest.horizon}
                          {row.nearest.horizonDate ? (
                            <span className="dir">
                              {" "}
                              · {row.nearest.horizonDate}
                            </span>
                          ) : null}
                        </td>
                        <td className="num">{row.nearest.rate.toFixed(3)}</td>
                      </>
                    ) : (
                      <td colSpan={2} style={{ color: "var(--text-muted)" }}>
                        {row.value?.missing_reason ??
                          "this lane published no path for this instant"}
                      </td>
                    )}
                  </tr>
                ))}
              </tbody>
            </table>
          </div>

          <BoardRead testId="macro-policy-read">
            {spread !== null ? (
              <>
                {served.length}/{rows.length} paths available · widest gap{" "}
                <b>
                  <span className="num">{(spread * 100).toFixed(0)}bp</span>
                </b>
                . No path is treated as the answer.
              </>
            ) : (
              <>
                Fewer than two paths published a rate; no gap is available.
              </>
            )}
          </BoardRead>
        </>
      )}
    </BoardPanel>
  );
}

/** Engine order is preserved: the payload publishes no severity to rank by. */
export function ContradictionFeed({
  domains,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
}) {
  const answered = CAUSAL_ORDER.filter((d) => domains[d].value !== null);
  const silent = CAUSAL_ORDER.filter((d) => domains[d].value === null);
  const rows = answered.flatMap((domain) =>
    (domains[domain].value?.contradictions ?? []).map((item) => ({
      domain,
      ...item,
    })),
  );

  return (
    <BoardPanel
      id="contradictions"
      title="Domain conflicts"
      questions={["Q3"]}
      basis="REAL"
      source={
        <>
          /api/macro/&#123;inflation,rates,usd,gold&#125; contradictions[] ·
          recomputed by the nightly macro_state_compute, never re-ranked here
        </>
      }
    >
      <p className="cap" data-testid="macro-contradiction-count">
        {plural(rows.length, "contradiction")} from{" "}
        {answered.length} of {CAUSAL_ORDER.length} domains that answered
      </p>

      {rows.map((row) => (
        <div
          className="contra"
          key={`${row.domain}-${row.rule}-${row.detail}`}
          data-testid={`macro-contradiction-row-${row.domain}`}
        >
          <b>
            {DOMAIN_LABEL[row.domain]} · {humanizeIdentifier(row.rule)}
          </b>
          <span data-raw-value={row.detail}>{humanizeText(row.detail)}</span>
        </div>
      ))}

      {rows.length === 0 ? (
        <p className="cap">
          {answered.length > 0
            ? "No domain rule fired; this is not a claim that the macro picture is consistent."
            : "No domain answered, so no rule was evaluated."}
        </p>
      ) : null}

      {silent.length > 0 ? (
        <p className="cap" data-testid="macro-contradiction-unasked">
          Not evaluated: {silent.map((d) => DOMAIN_LABEL[d]).join(", ")}.
        </p>
      ) : null}
    </BoardPanel>
  );
}

/** Cross-domain findings come from the assembler, never from a browser re-score. */
export function CrossDomainPanel({
  snapshot,
}: {
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
}) {
  const s = snapshot.value;
  const reasons = s?.reasons ?? [];

  return (
    <BoardPanel
      id="cross-domain"
      title="Chain conflicts"
      questions={["Q3", "Q4"]}
      basis="REAL"
      source={
        <>
          /api/macro/snapshot reasons[] ·{" "}
          {s
            ? `assembler ${s.assembler_version}, assembled ${instantUtc(s.assembled_at)}`
            : "no snapshot"}
        </>
      }
    >
      {/* Three states, and the third is the one that was a real bug: a dead API and an
          unassembled chain both arrived as `null` on the page this replaced, so a broken
          network printed "the chain was never assembled" — a claim about the assembler
          made on the evidence of a failed request. */}
      {snapshot.error ? (
        <div className="contra" data-testid="macro-chain-unreachable">
          <b>Chain unreachable · request failed</b>
          <span>{snapshot.error}</span>
          <span className="why">
            Domain states may still be valid; only the chain check is missing.
          </span>
        </div>
      ) : !s ? (
        <div className="contra" data-testid="macro-chain-unassembled">
          <b>Chain unassembled · never computed</b>
          <span>
            No snapshot exists for this instant.
          </span>
        </div>
      ) : (
        <>
          <p className="cap">
            status <b style={{ color: "var(--text-primary)" }}>{humanizeIdentifier(s.status)}</b> ·{" "}
            {plural(reasons.length, "finding")}
          </p>

          {STATUS_LEDE[s.status] ? (
            <p className="cap">{STATUS_LEDE[s.status]}</p>
          ) : null}

          {reasons.length > 0 ? (
            <div data-testid="macro-chain-refusal" data-status={s.status}>
              {reasons.map((reason, i) => (
                <div
                  className="contra"
                  key={`${reason.domain}-${reason.kind}-${i}`}
                  data-testid={`macro-chain-reason-${reason.domain}`}
                  style={i > 0 ? { marginTop: 8 } : undefined}
                >
                  <b>
                    {DOMAIN_LABEL[reason.domain as MacroDomainKey] ??
                      humanizeIdentifier(reason.domain)} · {humanizeIdentifier(reason.kind)}
                  </b>
                  <span data-raw-value={reason.detail}>{humanizeText(reason.detail)}</span>
                </div>
              ))}
            </div>
          ) : (
            // A clean verdict is NOT an empty panel. On a tab whose subject is the chain,
            // rendering nothing is indistinguishable from failing to load — and the
            // sentence has to bound its own claim, because "no finding" is a statement
            // about the checks that ran and not about whether the world makes sense.
            <div className="contra" data-testid="macro-chain-coherent">
              <b>No finding · internally coherent</b>
              <span>
                The chain is <b>internally coherent</b> under the checks that ran.
              </span>
              <span className="why">
                This is not a claim that the macro picture is right.
              </span>
            </div>
          )}
        </>
      )}
    </BoardPanel>
  );
}

/** `as_of` and `computed_at` remain separate because they answer different clocks. */
/** The replay verdict as one word for a table cell. `not_replaying` prints nothing — a
 *  live page has no instant to have answered for, and an empty cell says that better than
 *  the word "live" repeated five times. */
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

export function TransmissionHealth({
  domains,
  snapshot,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
}) {
  const publishers = [
    {
      id: "snapshot",
      label: "Chain snapshot",
      answered: snapshot.value !== null,
      error: snapshot.error,
      verdict: snapshot.verdict,
      answersFor: snapshot.value?.as_of,
      computed: snapshot.value?.assembled_at,
      freshness: null as string | null,
      ageHours: null as number | null,
    },
    ...CAUSAL_ORDER.map((domain) => ({
      id: domain,
      label: DOMAIN_LABEL[domain],
      answered: domains[domain].value !== null,
      error: domains[domain].error,
      verdict: domains[domain].verdict,
      answersFor: domains[domain].value?.as_of,
      computed: domains[domain].value?.computed_at,
      freshness: domains[domain].value?.freshness ?? null,
      ageHours: domains[domain].value?.age_hours ?? null,
    })),
  ];

  const edges = CAUSAL_ORDER.flatMap((domain) =>
    (domains[domain].value?.upstream ?? []).map((edge) => ({ domain, edge })),
  );

  return (
    <BoardPanel
      id="transmission"
      title="Data health"
      questions={["Q4", "Q7"]}
      basis="REAL"
      source={
        <>
          five publishers · as_of is what the replay bounds, computed_at is
          provenance and may legitimately be later
        </>
      }
    >
      <div className="tbl-wrap">
        <table>
          <thead>
            <tr>
              <th>Publisher</th>
              <th>Answered</th>
              <th>Answers for</th>
              <th>Computed</th>
              <th>Freshness</th>
            </tr>
          </thead>
          <tbody>
            {publishers.map((p) => {
              const status = p.error
                ? "request failed"
                : p.answered
                  ? "yes"
                  : "never computed";
              return (
                <tr
                  key={p.id}
                  data-testid={`macro-health-${p.id}`}
                  data-answered={status}
                >
                  <td>
                    {p.label}
                    {/* This tab stands on several publishers and they decline
                        SEPARATELY — the chain snapshot can be absent for an instant four
                        domains answered, and any one domain can be absent while the chain
                        is complete. So each publisher's replay verdict is read here beside
                        its own row rather than summarised into one desk-level sentence,
                        which is the reason this panel survives the withhold. */}
                    {verdictWord(p.verdict) ? (
                      <span className="dir"> · {verdictWord(p.verdict)}</span>
                    ) : null}
                  </td>
                  <td
                    style={{
                      color: p.error
                        ? "var(--negative)"
                        : p.answered
                          ? "var(--positive)"
                          : "var(--text-muted)",
                    }}
                  >
                    {status}
                  </td>
                  <td className="num">
                    {p.answersFor ? instantUtc(p.answersFor) : "—"}
                  </td>
                  <td className="num">
                    {p.computed ? instantUtc(p.computed) : "—"}
                  </td>
                  <td className="num">
                    {p.freshness
                      ? `${humanizeIdentifier(p.freshness)} · ${Math.round(p.ageHours ?? 0)}h`
                      : "—"}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>

      {/* The edge list keeps its established testid: it is the same claim the panel has
          always made — which upstream ANSWERS a downstream state consumed, printed
          verbatim and checked against nothing. */}
      <BoardRead testId="macro-transmission-edges">
        {edges.length > 0 ? (
          <>
            <b>
              {plural(edges.length, "upstream answer")} cited
            </b>{" "}
            by downstream domains:{" "}
            {edges
              .map(({ domain, edge }) =>
                `${DOMAIN_LABEL[domain]} ← ${humanizeIdentifier(edge.domain)} (${humanizeIdentifier(edge.state)})`,
              )
              .join(" · ")}
            .
          </>
        ) : (
          <>
            No answered domain cited an upstream state.
          </>
        )}
      </BoardRead>
    </BoardPanel>
  );
}
