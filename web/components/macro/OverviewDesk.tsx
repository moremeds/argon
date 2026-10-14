import type { components } from "@/lib/types";

import { BoardPanel, BoardSecTitle } from "./domain/BoardPanel";
import { GoldBreakdownSection } from "./goldFactor/GoldFactorBand";
import { SensitivityPanel } from "./goldFactor/GoldFactorPanels";
import type { GoldFactor, GoldFlows } from "./goldFactor/shared";
import {
  BoundaryPanel,
  ChainRail,
  EnergyProposalPanel,
} from "./overview/chain";
import { Zone } from "./overview/Zone";
import {
  MarketDeltasPanel,
  StateFlipsPanel,
  type DeltaSeries,
  type DomainWeek,
} from "./overview/zone1";
import {
  ContradictionFeed,
  CrossDomainPanel,
  PolicyPathsPanel,
  TransmissionHealth,
} from "./overview/zone2";
import { ConfidenceRepairPanel, FomcCalendarPanel } from "./overview/zone3";
import { ReplayStatus } from "./ReplayStatus";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "./types";
import { CAUSAL_ORDER, DOMAIN_LABEL } from "./types";

type PolicyComparison = components["schemas"]["PolicyComparison"];

/**
 * Tab 00 — the macro desk's overview, and the only tab whose subject is the other tabs.
 *
 * ## The board's own structure, not a list of cards
 *
 * The board divides this tab into four labelled zones — WHAT CHANGED, WHAT DISAGREES,
 * WHAT'S NEXT, then the chain as the anchor — and the zones are load-bearing. They are the
 * loop a macro PM actually runs in the morning, in order, and eleven panels without them
 * is a wall the reader has to sort themselves. The first port of this tab answered the
 * board's questions in argon's house typography with no zones at all; the information was
 * bound and the design was not, and the two bind together or the port is not done.
 *
 * ## What this is allowed to be
 *
 * It RE-PRESENTS what the other tabs already compute, and it computes nothing of its own.
 * Every panel below is a layout over fields that already exist on the wire, and each names
 * the field it lays out in its own provenance footer.
 *
 * It must never, and does not:
 *
 *  - **average, weight, blend or score the four domains.** Averaging four
 *    differently-grounded answers hides exactly the disagreements zone 2 exists to show,
 *    and `tests/unit/macroDesk.test.tsx` scans this component's own chrome for the
 *    vocabulary of one.
 *  - **derive a fifth number from the four.** No "macro regime", no risk level, no dial.
 *    The chain rail has four nodes and ends; there is no summary node.
 *  - **introduce an endpoint of its own.** Every route this tab reads is published by
 *    another tab: `/api/macro/*` by tabs 01–04, `/api/macro/policy` by tab 01,
 *    `/api/gold/{factor,flows,inputs}` by tab 05 and `/api/macro/dxy` by tab 04.
 *    The gold sensitivity and breakdown panels are tab 05's own components. If tab 00
 *    wants a value no tab publishes, that
 *    is a change to the domain that owns it, in that domain's PR.
 *  - **re-rank anything.** `MacroSnapshotStatus` is already worst-finding-wins; the
 *    per-domain contradictions publish no severity at all. An ordering invented here
 *    would be a judgement no engine made.
 *  - **restate, propagate or re-derive `duration_stance`.** A directional stance word may
 *    print only where the model produced it — inside the quarantined legacy scorecard on
 *    tab 02, nowhere else. This tab fetches neither `/api/rates/snapshot` nor the field.
 *
 * ## Why the replay chrome is shaped differently from tabs 01/02
 *
 * Those tabs stand on one publisher, so one `ReplayStatus` above the content says
 * everything. This tab stands on several, and blanking it because one declined would
 * destroy the only thing it is for. So the desk-level status speaks for the CHAIN
 * SNAPSHOT, every publisher's own verdict is read side by side in transmission health,
 * and content is withheld for the whole tab in exactly ONE case — `answered_after` on any
 * publisher. That verdict means the API did not apply `as_of`, and if it ignored the
 * parameter for one of these routes it ignored it for all of them, so everything below
 * would be live data under a replay heading. `unanswered` is NOT that case: a domain with
 * no state at an instant is that domain's own honest answer, and the panels say so per row.
 */
export function OverviewDesk({
  domains,
  week,
  snapshot,
  policy,
  deltas,
  factor,
  flows,
  priorLabel,
  nowLabel,
  windowLabel,
}: {
  domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>>;
  week: DomainWeek;
  snapshot: MacroOverviewSlot<MacroContextSnapshot>;
  policy: { value: PolicyComparison | null; error?: string };
  deltas: DeltaSeries[];
  factor: { value: GoldFactor | null; error?: string };
  flows: { value: GoldFlows | null; error?: string };
  priorLabel: string;
  nowLabel: string;
  windowLabel: string;
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
  const withheld = wrongInstant.length > 0;
  const lastFactor = factor.value?.points.at(-1);

  return (
    <div className="board" data-testid="macro-overview">
      <BoardSecTitle
        title="Overview"
        questions={["Q1", "Q2", "Q3", "Q4", "Q6"]}
      >
        State changes, disagreements, next catalysts and chain health. Each
        domain remains independent; no composite score is produced.
      </BoardSecTitle>

      <ReplayStatus
        verdict={snapshot.verdict}
        publisher="macro context snapshot"
        // The macro routes select `WHERE as_of <= %s` and tie-break on the LATER
        // `computed_at`, so `as_of` is the clock the request bounds and `computed_at` is
        // provenance. Feeding the verdict `computed_at` here would withhold a state that
        // was legitimately recomputed after the instant it answers for.
        clock="instant"
      />

      {withheld ? (
        <div className="note-refuse" data-testid="macro-overview-wrong-instant">
          <b>WITHHELD — THE REPLAY DATE WAS NOT APPLIED</b>{" "}
          {wrongInstant.map((p) => p.label).join(", ")} answered with a state
          from after the instant that was asked for. On these routes the request
          bounds the answer&rsquo;s own <code>as_of</code>, so that can only
          mean the parameter was not applied — and if it was dropped for one of
          these reads it was dropped for all of them. Everything below would be
          today&rsquo;s desk under a replay heading, so it is withheld.
          Transmission health stays, because it is the diagnosis.
        </div>
      ) : null}

      {withheld ? (
        <div className="grid" style={{ marginTop: 14 }}>
          <TransmissionHealth domains={domains} snapshot={snapshot} />
        </div>
      ) : (
        <>
          <Zone
            first
            kicker="Zone 1"
            label="Changed"
            scope={`${priorLabel} → ${nowLabel}`}
          />
          <div className="grid g3">
            <StateFlipsPanel
              week={week}
              priorLabel={priorLabel}
              nowLabel={nowLabel}
            />
            <MarketDeltasPanel series={deltas} windowLabel={windowLabel} />
            {lastFactor ? (
              <SensitivityPanel last={lastFactor} />
            ) : (
              <BoardPanel
                id="gold-factor-sensitivity"
                title="Gold sensitivity"
                questions={["Q4"]}
                basis="REAL"
                source="/api/gold/factor · gold_factor_daily"
              >
                <p className="cap">
                  {factor.error ??
                    (snapshot.verdict.kind === "not_replaying"
                      ? "Not computed yet."
                      : "Live data; not shown in replay.")}
                </p>
              </BoardPanel>
            )}
          </div>

          {factor.value && lastFactor ? (
            <GoldBreakdownSection
              data={factor.value}
              flows={flows.value}
              scope={`through ${factor.value.last_date}`}
            />
          ) : null}

          <Zone
            kicker="Zone 2"
            label="Disagreements"
            scope="the raw material of trades"
          />
          <div className="grid g2">
            <PolicyPathsPanel policy={policy} />
            <ContradictionFeed domains={domains} />
          </div>
          <div className="grid g2" style={{ marginTop: 12 }}>
            <CrossDomainPanel snapshot={snapshot} />
            <TransmissionHealth domains={domains} snapshot={snapshot} />
          </div>

          <Zone
            kicker="Zone 3"
            label="Next"
            scope="dated events that confirm or falsify"
          />
          <div className="grid g2">
            <FomcCalendarPanel policy={policy} />
            <ConfidenceRepairPanel domains={domains} />
          </div>

          <Zone
            kicker="Anchor"
            label="Chain"
            scope="Q1 Q4 · tabs 01–04 unfold each node"
          />
          <ChainRail
            domains={domains}
            reasons={snapshot.value?.reasons ?? []}
            goldShare={lastFactor?.explained_share}
          />
          <div className="grid g2" style={{ marginTop: 12 }}>
            <EnergyProposalPanel />
            <BoundaryPanel />
          </div>
        </>
      )}
    </div>
  );
}
