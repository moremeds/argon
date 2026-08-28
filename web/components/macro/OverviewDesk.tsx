import { ReplayStatus } from "./ReplayStatus";
import { DomainStateCard } from "./DomainStateCard";
import { ContradictionFeed } from "./overview/ContradictionFeed";
import { CrossDomainPanel } from "./overview/CrossDomainPanel";
import { DailyLoop } from "./overview/DailyLoop";
import { MONO_LABEL } from "./overview/Panel";
import { TransmissionHealth } from "./overview/TransmissionHealth";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "./types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "./types";

/**
 * Tab 00 — the macro desk's overview, and the only tab whose subject is the other tabs.
 *
 * ## What this is allowed to be
 *
 * It RE-PRESENTS what the other tabs already compute, and it computes nothing of its own.
 * Its five requests — `/api/macro/snapshot` plus the four domain states — return the same
 * responses tabs 03-05 will render, arranged for a morning read. Every panel below is a
 * layout over fields that already exist on the wire, and each one names the field it lays
 * out in its own lede.
 *
 * It must never, and does not:
 *
 *  - **average, weight, blend or score the four domains.** §1 of the port plan and §9
 *    invariant 1. Averaging four differently-grounded answers hides exactly the
 *    disagreements the cards exist to show, and `tests/unit/macroDesk.test.tsx` scans this
 *    component's own chrome for the vocabulary of one.
 *  - **derive a fifth number from the four.** No "macro regime", no risk level, no dial.
 *    Four states in causal order is four states; a fifth row summarising them would be the
 *    composite wearing a table's clothes.
 *  - **introduce an endpoint of its own.** If tab 00 wants a value no tab publishes, that
 *    is a change to the domain that owns it, in that domain's PR.
 *  - **re-rank anything.** `MacroSnapshotStatus` is already worst-finding-wins and its four
 *    values are kept deliberately distinguishable (`macro/snapshot.py:30-33`); the
 *    per-domain contradictions publish no severity at all. An ordering invented here would
 *    be a judgement no engine made.
 *  - **restate, propagate or re-derive `duration_stance`.** Settled by the operator
 *    2026-08-28 (plan §10-I): the word `BUY`/`SELL` may print where the model produced it,
 *    which is inside the quarantined legacy `RatesScorecard` on tab 02, and nowhere else.
 *    Tab 00 is named in that ruling. It fetches neither `/api/rates/snapshot` nor
 *    `/api/macro/policy`, so the field is not even in reach here.
 *
 * ## Why the replay chrome is shaped differently from tabs 01/02
 *
 * Those tabs stand on one publisher, so one `ReplayStatus` above the content plus
 * `replayWithholdsContent` says everything. This tab stands on five, and blanking it
 * because one of five declined would destroy the only thing it is for. So:
 *
 *  - the desk-level `ReplayStatus` speaks for the CHAIN SNAPSHOT, the publisher whose
 *    subject is all four domains at once;
 *  - every publisher's own verdict is read side by side in the transmission-health panel;
 *  - content is withheld for the whole tab in exactly ONE case — `answered_after` on any
 *    publisher. That verdict means the API did not apply `as_of`, and if it ignored the
 *    parameter for one of these five routes it ignored it for all of them, so everything
 *    below would be live data under a replay heading. `unanswered` is NOT that case: a
 *    domain with no state at an instant is that domain's own honest answer, and the panels
 *    already say so per row.
 */
export function OverviewDesk({
  domains,
  snapshot,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
}) {
  const publishers = [
    { label: "the chain snapshot", slot: snapshot },
    ...CAUSAL_ORDER.map((domain) => ({
      label: DOMAIN_LABEL[domain],
      slot: domains[domain],
    })),
  ];
  const wrongInstant = publishers.filter(
    (p) => p.slot.verdict.kind === "answered_after",
  );

  return (
    <div
      data-testid="macro-overview"
      style={{
        padding: 24,
        maxWidth: 1100,
        margin: "0 auto",
        color: "var(--text-primary)",
      }}
    >
      <header style={{ marginBottom: 16 }}>
        <h1 style={{ margin: 0, fontSize: 20, fontWeight: 600 }}>
          Overview · Daily Loop
        </h1>
        <p
          style={{
            margin: "6px 0 0",
            fontSize: 13,
            lineHeight: 1.55,
            color: "var(--text-secondary)",
            maxWidth: 780,
          }}
        >
          Everything on this tab is published by another tab&rsquo;s publisher and
          rearranged here for a morning read. Nothing is averaged, ranked or scored across
          the four domains, and there is no fifth number: the desk shows four separately
          grounded answers and the assembler&rsquo;s verdict on whether they belong
          together, which is the one thing no single answer can say about itself.
        </p>
      </header>

      <ReplayStatus
        verdict={snapshot.verdict}
        publisher="macro context snapshot"
        // The macro routes select `WHERE as_of <= %s` and tie-break on the LATER
        // `computed_at`, so `as_of` is the clock the request bounds and `computed_at` is
        // provenance. Feeding the verdict `computed_at` here would withhold a state that
        // was legitimately recomputed after the instant it answers for.
        answerClock="state_as_of"
      />

      {wrongInstant.length > 0 ? (
        <section
          data-testid="macro-overview-wrong-instant"
          style={{
            margin: "16px 0 0",
            padding: "12px 14px",
            borderLeft: "3px solid var(--negative)",
            background: "var(--bg-panel)",
          }}
        >
          <p style={{ ...MONO_LABEL, margin: 0, color: "var(--negative)" }}>
            Withheld — the replay date was not applied
          </p>
          <p
            style={{
              margin: "6px 0 0",
              fontSize: 12.5,
              lineHeight: 1.55,
              color: "var(--text-secondary)",
              maxWidth: 780,
            }}
          >
            {wrongInstant.map((p) => p.label).join(", ")} answered with a state from after
            the instant that was asked for. On these routes the request bounds the
            answer&rsquo;s own <code>as_of</code>, so that can only mean the parameter was
            not applied — and if it was dropped for one of these five reads it was dropped
            for all of them. Everything below would be today&rsquo;s desk under a replay
            heading, so it is withheld. Transmission health stays, because it is the
            diagnosis.
          </p>
        </section>
      ) : null}

      <div style={{ display: "grid", gap: 14, marginTop: 16 }}>
        {wrongInstant.length === 0 ? (
          <>
            <DailyLoop domains={domains} />
            <CrossDomainPanel snapshot={snapshot} />
            <ContradictionFeed domains={domains} />
          </>
        ) : null}

        <TransmissionHealth domains={domains} snapshot={snapshot} />

        {wrongInstant.length === 0 ? (
          <FullStates domains={domains} snapshot={snapshot} />
        ) : null}
      </div>
    </div>
  );
}

/**
 * The four states in full, each with what it stood on.
 *
 * Carried from the `/macro` page this tab replaces — `DomainStateCard` and the
 * per-domain chain flag are unchanged, and the flag is still prefixed with the domain
 * name because it sits between two cards and without one it reads as belonging to the
 * card above it.
 *
 * Not folded into the daily loop: the loop is the ten-second scan and these are the
 * evidence. The one thing that moved is the confidence arithmetic, which now sits under
 * each card's confidence number instead of being listed raw inside its disclosure.
 */
function FullStates({
  domains,
  snapshot,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
}) {
  const refusedBy = new Map(
    (snapshot.value?.reasons ?? []).map((reason) => [reason.domain, reason]),
  );

  return (
    <section>
      <h2
        style={{
          margin: 0,
          fontFamily: "var(--font-mono), monospace",
          fontSize: 11,
          letterSpacing: 1.5,
          textTransform: "uppercase",
          color: "var(--text-primary)",
          fontWeight: 600,
        }}
      >
        The four states, in full
      </h2>
      <p
        style={{
          margin: "5px 0 12px",
          fontSize: 12,
          lineHeight: 1.5,
          color: "var(--text-secondary)",
          maxWidth: 780,
        }}
      >
        Each state as its own engine published it, with the confidence terms behind the
        number and the observations it cited. Stored answers replayed, never recomputed at
        read time.
      </p>

      <div style={{ display: "grid", gap: 10 }}>
        {CAUSAL_ORDER.map((domain, i) => (
          <div key={domain} style={{ display: "grid", gap: 10 }}>
            <div style={{ display: "grid", gap: 6 }}>
              {refusedBy.has(domain) ? (
                <div
                  data-testid={`macro-chain-flag-${domain}`}
                  style={{
                    fontSize: 12,
                    color: "var(--danger, #a33)",
                    padding: "2px 2px 0",
                  }}
                >
                  <strong>{DOMAIN_LABEL[domain]}:</strong>{" "}
                  {refusedBy.get(domain)?.detail}
                </div>
              ) : null}
              <DomainStateCard
                domain={domain}
                slot={{
                  value: domains[domain].value,
                  error: domains[domain].error,
                }}
              />
            </div>
            {i < CAUSAL_ORDER.length - 1 ? (
              <div
                aria-hidden
                style={{
                  justifySelf: "center",
                  color: "var(--text-muted)",
                  fontSize: 14,
                  lineHeight: 1,
                }}
              >
                ↓
              </div>
            ) : null}
          </div>
        ))}
      </div>
    </section>
  );
}
