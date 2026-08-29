import type { components } from "@/lib/types";

import { BoardPanel, BoardRead } from "../domain/BoardPanel";
import { instantUtc, plural} from "../format";
import type { ReplayVerdict } from "../replay";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "../types";
import { CAUSAL_ORDER, DOMAIN_LABEL, STATUS_LEDE } from "../types";

/**
 * ZONE 2 · WHAT DISAGREES — the board's four middle panels.
 *
 * The board's own kicker for this zone is "the raw material of trades", and the four
 * panels are deliberately two pairs at two levels. Contradictions INSIDE a domain and
 * contradictions BETWEEN domains are different objects published by different engines,
 * and the desk keeps them in separate panels because merging them would make an
 * assembler's verdict look like a domain's finding.
 */

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
  { key: "actual", label: "Actual · the committee has done" },
  { key: "committee_projection", label: "Committee · SEP projection" },
  { key: "dealer_expectations", label: "Dealers · NY Fed survey" },
  { key: "market_implied", label: "Market · what is priced" },
];

/** The lane's nearest-horizon rate, which is the number the board's table compares across
 *  lanes. `null` when the lane published no path — the four lanes decline independently
 *  and one missing lane must never blank the comparison. */
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

/**
 * PANEL 4 · Four policy paths · who says what.
 *
 * ### A missing lane is the panel's content, not its failure
 *
 * `market_implied` publishes a `missing_reason` rather than a path on this desk today
 * ("no PIT-eligible market implied policy release"). The board draws four lanes; the
 * honest port draws four ROWS, three carrying a number and one carrying the publisher's
 * own sentence about why it has none. Dropping the row would silently turn a four-way
 * comparison into a three-way one and nothing on the page would say so.
 */
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
      title="Four policy paths · who says what"
      questions={["Q2", "Q3"]}
      basis="REAL"
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
                {served.length} of {rows.length} lanes published a
                nearest-horizon rate, and they span{" "}
                <b>
                  <span className="num">{(spread * 100).toFixed(0)}bp</span>
                </b>
                . The spread IS the disagreement — it is what the lanes were
                separated for, and the desk reports it without deciding which
                lane is right.
              </>
            ) : (
              <>
                Fewer than two lanes published a rate, so there is no spread to
                report. A comparison needs two things to compare.
              </>
            )}
          </BoardRead>
        </>
      )}
    </BoardPanel>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * PANEL 5 · Contradictions inside a domain
 * ──────────────────────────────────────────────────────────────────────────── */

/**
 * PANEL 5 · Contradiction feed · engine-reported.
 *
 * Every contradiction rule that fired INSIDE a domain, gathered from the four states.
 *
 * ### It is a list. It must never become a ranking
 *
 * The engine publishes a `rule` and a `detail` and nothing else — no weight, no level, no
 * score — so any ordering beyond the producer's would be invented at the browser. The
 * order is the engine's causal order across domains and the engine's emission order
 * within one. Sorting these would tell the reader which contradiction matters most, a
 * judgement no engine on this desk made.
 *
 * ### The count carries its own denominator
 *
 * A quiet feed because nothing fired and a quiet feed because three engines never ran look
 * identical, and only one is good news. So the summary names both numbers and the silent
 * domains are listed rather than silently shrinking the denominator.
 */
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
      title="Contradiction feed · engine-reported"
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
            {DOMAIN_LABEL[row.domain]} · {row.rule.replace(/_/g, " ")}
          </b>
          <span>{row.detail}</span>
        </div>
      ))}

      {rows.length === 0 ? (
        <p className="cap">
          {answered.length > 0
            ? "No contradiction rule fired inside any domain that answered. That is a statement about the rules that ran, not a claim that the macro picture is consistent."
            : "No domain answered, so no contradiction rule was evaluated. An empty feed here means nothing was asked, not that nothing fired."}
        </p>
      ) : null}

      {silent.length > 0 ? (
        <p className="cap" data-testid="macro-contradiction-unasked">
          Not represented: {silent.map((d) => DOMAIN_LABEL[d]).join(", ")} —{" "}
          {silent.length === 1 ? "it contributed" : "they contributed"} no rows
          because {silent.length === 1 ? "it has" : "they have"} no state to
          evaluate at this instant, not because{" "}
          {silent.length === 1 ? "it is" : "they are"} uncontradicted.
        </p>
      ) : null}
    </BoardPanel>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * PANEL 6 · Contradictions between domains
 * ──────────────────────────────────────────────────────────────────────────── */

/**
 * PANEL 6 · Cross-domain contradictions.
 *
 * The assembler's verdict, which is the one question no single domain can answer about
 * itself: do these four belong together. `MacroSnapshotReason` is a defect BETWEEN
 * domains and is not the same object as a domain's own contradiction — the two live in
 * different places and this desk keeps them in different panels.
 *
 * The snapshot's own failure renders as an unassembled chain, never as a clean one: a
 * missing verdict must never be able to look like a passing verdict.
 */
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
      title="Cross-domain contradictions · the assembler's verdict"
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
            This is a fact about our API, not the assembler declining. The four
            nodes on the rail may still be perfectly good answers; what is
            missing is the check on whether they belong together.
          </span>
        </div>
      ) : !s ? (
        <div className="contra" data-testid="macro-chain-unassembled">
          <b>Chain unassembled · never computed</b>
          <span>
            No snapshot was assembled for this instant, so nothing has checked
            whether the four domains belong together.
          </span>
        </div>
      ) : (
        <>
          <p className="cap">
            status <b style={{ color: "var(--text-primary)" }}>{s.status}</b> ·{" "}
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
                      reason.domain}{" "}
                    · {reason.kind}
                  </b>
                  <span>{reason.detail}</span>
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
                The assembler held every domain it expected and found nothing to
                report between them, so the chain is <b>internally coherent</b>{" "}
                at this instant.
              </span>
              <span className="why">
                That is a statement about the checks that ran — it is not a
                claim that the macro picture is right.
              </span>
            </div>
          )}
        </>
      )}
    </BoardPanel>
  );
}

/* ────────────────────────────────────────────────────────────────────────────
 * PANEL 7 · Transmission health
 * ──────────────────────────────────────────────────────────────────────────── */

/**
 * PANEL 7 · Transmission health.
 *
 * Did each of tab 00's publishers answer, and what did it answer for. Two clocks are
 * shown APART on purpose: `as_of` is the instant the stored answer answers for and the
 * only clock the replay request bounds; `computed_at` is provenance and may legitimately
 * be much later, because a later recompute of the same instant is legal. One column
 * carrying both is how the second gets read as the first.
 *
 * The upstream edge list underneath is printed verbatim and checked against nothing —
 * whether a cited upstream is the one the chain holds is the assembler's verdict, above.
 * Re-deciding it here would be a second opinion computed in a browser.
 */
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
      title="Transmission health · did each publisher answer"
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
                      ? `${p.freshness} · ${Math.round(p.ageHours ?? 0)}h`
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
              .map(
                ({ domain, edge }) =>
                  `${DOMAIN_LABEL[domain]} ← ${edge.domain} #${edge.upstream_state_id} (${edge.state})`,
              )
              .join(" · ")}
            . Whether a cited answer is the one the chain holds is the
            assembler&rsquo;s verdict, not this panel&rsquo;s.
          </>
        ) : (
          <>
            No domain that answered cited an upstream answer. Inflation and
            policy stand on observations alone, so an empty edge list is their
            normal shape and not a broken link — only a transmission domain has
            any.
          </>
        )}
      </BoardRead>
    </BoardPanel>
  );
}
