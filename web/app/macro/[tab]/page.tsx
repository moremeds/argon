import { notFound } from "next/navigation";

import { DesignNotes } from "@/components/macro/DesignNotes";
import { DomainStateTab } from "@/components/macro/DomainStateTab";
import { BoardSecTitle } from "@/components/macro/domain/BoardPanel";
import {
  DeliveryFormPanel,
  ExportRefusalPanel,
  FactorVectorPanel,
  type FactorExportSlots,
} from "@/components/macro/domain/FactorExport";
import {
  EnergyDisciplinePanel,
  EnergyInventoryPanel,
  EnergyProposedPanels,
  EnergyRoutePanel,
} from "@/components/macro/domain/EnergyProposal";
import { OverviewDesk } from "@/components/macro/OverviewDesk";
import { ReplayControl } from "@/components/macro/ReplayControl";
import { ReplayStatus } from "@/components/macro/ReplayStatus";
import type { MacroDomainSlot } from "@/components/macro/types";
import {
  parseReplayRequest,
  replayVerdict,
  replayVerdictForDomainState,
  replayWithholdsContent,
  todayUtcDate,
} from "@/components/macro/replay";
import {
  VALID_TABS,
  macroTabHref,
  type MacroTabContent,
  type MacroTabProps,
  type MacroTabSlug,
} from "@/components/macro/tabs";
import type {
  MacroContextSnapshot,
  MacroDomainKey,
  MacroDomainState,
  MacroOverviewSlot,
} from "@/components/macro/types";
import { CurveDesk } from "@/components/rates/CurveDesk";
import { FedDesk } from "@/components/rates/FedDesk";
import { settle } from "@/components/rates/deskShared";
import { api } from "@/lib/api";

import { GoldTab } from "./goldTab";

// Per-route rather than per-page-load: each tab reads 1-3 live endpoints, and the `as_of`
// searchParam P4 added must re-fetch on the server rather than be served from the RSC
// Router Cache. Declared before that landed so no tab could inherit a cached shell by
// accident; now load-bearing.
export const dynamic = "force-dynamic";

/** The publisher each replay banner speaks for, named the way an operator would name it
 *  rather than by endpoint. Both tabs stand on the same one. */
const RATES_PUBLISHER = "rates snapshot";

/**
 * Tab 01 — Fed · Policy.
 *
 * Two publishers, settled independently. Carried from `app/rates/page.tsx`, whose
 * comment said why: the snapshot and the policy comparison come from different jobs, so
 * if the policy release ingest is down the curve is still a fact and the tab should say
 * which half is missing rather than blanking both.
 *
 * It deliberately does NOT also call `/api/macro/rates`. The `MacroStateSummary` the
 * state panel renders is the `state` field on `RatesSnapshotResponse`, which
 * `routers/rates.py` attaches at READ time from the same repository read at the same
 * resolved instant that `/api/macro/rates` performs. `models/rates.py` says the field is
 * not persisted because "copying it here would fork one answer into two records that
 * could disagree"; a second HTTP fetch of the same shape forks one answer into two
 * requests that could disagree, which is the same defect one layer up.
 *
 * REPLAY: both requests take the same `as_of`, and the banner is driven by the SNAPSHOT's
 * `computed_at` alone. `/api/macro/policy` cannot drive it — `PolicyComparison.as_of` is
 * `as_of=as_of`, the requested instant echoed straight back (`macro/policy_report.py:128`),
 * so a banner keyed on it would be a banner keyed on the request, which is precisely the
 * thing §8 of the plan says must not happen. What the policy publisher does carry is a
 * release date per lane, which `PolicyPathComparison` already prints inside each lane; the
 * desk-level banner does not claim to have checked it.
 */
async function FedTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : undefined;
  const [snapshot, policy, ratesState] = await Promise.all([
    settle(() => api.ratesSnapshot(asOf), "rates API"),
    settle(() => api.macroPolicy(asOf), "macro policy API"),
    // The board's named fallback for the state panel, cited at the same instant and
    // settled separately. See `FedDesk`'s `ratesState` prop: the snapshot's own state
    // block is gated behind a flag that defaults OFF, and with it off the board's
    // "State & confidence" panel had nothing to render. The docstring above still holds
    // where it applies — when the flag IS on, the snapshot's block wins and this is
    // ignored, so no answer is ever forked into two requests.
    settle(() => api.macroDomainState("rates", asOf), "rates state API"),
  ]);

  const verdict = replayVerdict(replay, {
    computedAt: snapshot.value?.computed_at,
    failed: Boolean(snapshot.error),
  });
  const status = (
    <ReplayStatus
      verdict={verdict}
      publisher={RATES_PUBLISHER}
      clock="instant"
    />
  );
  if (replayWithholdsContent(verdict)) return status;

  return (
    <>
      {status}
      <FedDesk
        snapshot={snapshot.value}
        errorMessage={snapshot.error}
        policyComparison={policy.value}
        policyComparisonError={policy.error}
        ratesState={ratesState.value}
      />
    </>
  );
}

/**
 * Tab 02 — Rates · Curve.
 *
 * TWO publishers since 2026-08-29, where the comment here used to say one.
 *
 * The snapshot carries supply, positioning and funding as READINGS. The engine's verdict
 * on each — `IN_RANGE · FLAT`, and the confidence behind it — lives on `/api/macro/rates`
 * as `sub_states`, which the board prints as three panels and this tab never fetched. The
 * two are worth having together: the readings without the verdict make the reader do the
 * engine's job, and the verdict without the readings hides what it stands on.
 *
 * Settled separately, and the banner stays keyed on the SNAPSHOT alone. The two endpoints
 * select on different columns — `/api/rates/snapshot` on `computed_at`, `/api/macro/*` on
 * `as_of` — so a banner driven by whichever answered would be a banner that changes its
 * meaning depending on which publisher was up. The cited half degrades to its readings.
 */
async function CurveTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : undefined;
  const [snapshot, ratesState] = await Promise.all([
    settle(() => api.ratesSnapshot(asOf), "rates API"),
    settle(() => api.macroDomainState("rates", asOf), "rates state API"),
  ]);

  const verdict = replayVerdict(replay, {
    computedAt: snapshot.value?.computed_at,
    failed: Boolean(snapshot.error),
  });
  const status = (
    <ReplayStatus
      verdict={verdict}
      publisher={RATES_PUBLISHER}
      clock="instant"
    />
  );
  if (replayWithholdsContent(verdict)) return status;

  return (
    <>
      {status}
      <CurveDesk
        snapshot={snapshot.value}
        errorMessage={snapshot.error}
        subStates={ratesState.value?.sub_states}
      />
    </>
  );
}

/**
 * Tabs 03 and 04 — Inflation and US Dollar. One publisher each, and the same shape twice,
 * so they share one implementation rather than two copies that drift.
 *
 * §3's binding table gives each of these exactly ONE request, and that is the whole tab:
 * `/api/macro/{domain}` returns the stored state, its confidence terms, its
 * contradictions, its upstream dependencies and the evidence rows it cited. There is
 * nothing to settle against a second clock and nothing to compose.
 *
 * REPLAY: gated by `replayVerdictForDomainState`, not by `replayVerdict`. The two endpoint
 * families filter different columns — `/api/rates/snapshot` on `computed_at`,
 * `/api/macro/*` on `as_of` — and gating a domain state on `computed_at` would withhold a
 * correctly backfilled answer as though a deploy race had produced it. The reasoning, with
 * the storage citations, is at the function.
 *
 * The `null` value is a real state and not an error: `api.macroDomainState` passes
 * `allow404`, and `_domain_state` 404s deliberately rather than recomputing — "the honest
 * reply to 'what did you think in March' is 'nothing was recorded'". So the slot stays
 * three-state all the way to the card (§9 invariant 2).
 */
function domainTab(
  domain: "inflation" | "usd",
  publisher: string,
): MacroTabContent {
  return async function DomainTab({ replay }: MacroTabProps) {
    const asOf = replay.kind === "replay" ? replay.asOf : undefined;
    // Tab 03's expectations panel needs the market-implied leg, and that series belongs
    // to the rates domain — the board's own row says "(single owner)". So it is CITED at
    // the same instant, settled separately: a rates outage must cost inflation one leg of
    // one panel, not the whole tab. Tab 04 asks for nothing extra and pays for nothing.
    const [state, citedRates] = await Promise.all([
      settle(() => api.macroDomainState(domain, asOf), `${domain} state API`),
      domain === "inflation"
        ? settle(() => api.macroDomainState("rates", asOf), "rates state API")
        : Promise.resolve({ value: null, error: undefined }),
    ]);

    const verdict = replayVerdictForDomainState(replay, {
      asOf: state.value?.as_of,
      computedAt: state.value?.computed_at,
      failed: Boolean(state.error),
    });
    const status = (
      <ReplayStatus verdict={verdict} publisher={publisher} clock="instant" />
    );
    if (replayWithholdsContent(verdict)) return status;

    const slot: MacroDomainSlot = { value: state.value, error: state.error };
    return (
      <>
        {status}
        <DomainStateTab
          domain={domain}
          slot={slot}
          citedRates={citedRates.value}
          citationError={citedRates.error}
        />
      </>
    );
  };
}

/**
 * Tab 00 — Overview · Daily Loop.
 *
 * FIVE publishers, the only tab on the desk with more than three, and the reason is
 * structural: it is the tab whose subject is the other tabs. `/api/macro/snapshot` for the
 * chain verdict, plus one call per domain for the four answers it is a verdict about.
 *
 * ONE CALL PER DOMAIN rather than a bundle, carried from the `/macro` page this replaces:
 * the four engines run on separate schedules and any of them can be absent, so a bundling
 * endpoint would make one missing state look like a failed page — and saying which half is
 * missing is the whole job. `api.macroDomainState` allows a 404 through as `null`, which
 * is a fact to render, not an error to throw.
 *
 * THE SNAPSHOT IS FETCHED BESIDE THE FOUR, NEVER INSTEAD OF THEM (§9 invariant 8). It
 * answers the one question none of them can — whether they belong together — and its own
 * failure renders as an unreachable-chain notice, never as a clean chain.
 *
 * REPLAY: all five take the same `as_of` date and all five carry an answer clock. The
 * verdict is driven by each response's `as_of` (the instant the stored answer answers for)
 * and NOT by `computed_at`, because these routes select `WHERE as_of <= %s` and tie-break
 * on the LATER `computed_at` — `storage/macro_domain_state.py:216-219` states that a later
 * recompute of the same instant is legitimate, so a `computed_at` check would withhold a
 * state the contract permits. `as_of` is the request's own bound echoed back, so the check
 * fails exactly when the API did not apply the parameter, which is what it is for.
 */
async function OverviewTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : undefined;
  const [inflation, rates, usd, gold, snapshot] = await Promise.all([
    settle(
      () => api.macroDomainState("inflation", asOf),
      "inflation state API",
    ),
    settle(() => api.macroDomainState("rates", asOf), "policy/rates state API"),
    settle(() => api.macroDomainState("usd", asOf), "USD state API"),
    settle(() => api.macroDomainState("gold", asOf), "gold state API"),
    settle(() => api.macroContextSnapshot(asOf), "macro context snapshot API"),
  ]);

  /** One settled fetch plus what it answered for. `as_of` is the clock — see above. */
  /**
   * One settled fetch plus the verdict on what it answered for.
   *
   * `replayVerdictForDomainState`, not `replayVerdict`, and the two instants are kept
   * APART. This tab was written on a branch where `ReplayStatus` took an `answerClock`
   * and this helper passed `as_of` in the field named `computedAt` to select the
   * "answers for" wording. That prop is gone; `ReplayStatus` now says "That answer was
   * computed …" for every instant tab, and feeding it an `as_of` under that sentence
   * would print one instant under the other's name.
   *
   * So the gate reads `as_of` — the instant the stored answer answers for, which is what
   * `/api/macro/*` selects on — and the sentence reads the real `computed_at`. Both are
   * then true. A state legitimately recomputed after the instant it answers for is still
   * shown, which is the behaviour `storage/macro_domain_state.py:216-219` requires.
   *
   * The snapshot's build instant is `assembled_at`, not `computed_at`; it is passed in by
   * the caller rather than guessed here, so a shape without one cannot silently report
   * `undefined` as its provenance.
   */
  const withVerdict = <T extends { as_of: string }>(
    settled: { value: T | null; error?: string },
    computedAt?: (value: T) => string | undefined,
  ): MacroOverviewSlot<T> => ({
    value: settled.value,
    error: settled.error,
    verdict: replayVerdictForDomainState(replay, {
      asOf: settled.value?.as_of,
      computedAt: settled.value ? computedAt?.(settled.value) : undefined,
      failed: Boolean(settled.error),
    }),
  });

  const domains: Record<MacroDomainKey, MacroOverviewSlot<MacroDomainState>> = {
    inflation: withVerdict(inflation, (v) => v.computed_at),
    // The API path segment is `rates`; the domain key the store and the causal order use
    // is `policy_rates`. Mapped here rather than anywhere downstream, so exactly one place
    // knows the two vocabularies differ.
    policy_rates: withVerdict(rates, (v) => v.computed_at),
    usd: withVerdict(usd, (v) => v.computed_at),
    gold: withVerdict(gold, (v) => v.computed_at),
  };

  return (
    <OverviewDesk
      domains={domains}
      snapshot={withVerdict<MacroContextSnapshot>(
        snapshot,
        (v) => v.assembled_at,
      )}
    />
  );
}

/**
 * Registered slug -> its content.
 *
 * Keyed by `MacroTabSlug`, which is derived from `VALID_TABS` itself, so this map and
 * the registry cannot drift: adding a tab to the registry without adding its content
 * here fails typecheck rather than 404ing at runtime.
 *
 * ### The signature, and why it is this one
 *
 * `MacroTabContent` is `(props: MacroTabProps) => ReactElement | Promise<ReactElement>`,
 * where `MacroTabProps` is `{ replay: MacroReplayRequest }`. Every later tab — P5's tab
 * 00, P6's tabs 03/04/05 — is typechecked against it, so the four choices inside it are
 * worth stating rather than inferring.
 *
 * **It returns an element, sync or async.** Tabs 01 and 02 await their own publishers on
 * the server; a bare `() => ReactElement` would have forced their fetches up into this
 * page, which means one shared fetch for tabs that do not need the same data (§3's
 * binding table gives each tab 1-3 requests of its own, and tab 00 five).
 *
 * **It takes a PROPS OBJECT, not a positional argument.** These are components,
 * instantiated as `<Content replay={…} />`. Calling them as functions —
 * `{await Content(replay)}` — would collapse each tab into this page's own render: no
 * per-tab Suspense boundary, no per-tab error boundary, and the streaming behaviour of
 * `loading.tsx` lost. A props object is also the only shape that can gain a second field
 * without editing every tab that ignores it.
 *
 * **It carries the REQUEST, not a resolved instant and not fetched data.** Two reasons.
 * A resolved instant (`Date`, or a UTC timestamp) throws away which question was asked —
 * §3.1 records three different clocks behind the same word "as of", and tab 05 will hand
 * the same date to `/api/gold/replay` as an `obs_date` matched with exact equality, not as
 * an instant. And fetched data cannot be hoisted here at all without making the shared
 * fetch this signature exists to avoid.
 *
 * **It carries a DISCRIMINATED UNION, not `asOf: string | null`.** The narrower type is
 * enough for the two tabs that exist, and that is exactly the trap: `rejected` would
 * collapse into `live`, so a tab could not tell "he asked for nothing" from "he asked for
 * something unreadable". The union is also what makes the next widening safe — the day
 * the desk wants intraday replay, `as_of_ts` becomes a variant and every tab that matches
 * on `kind` gets a compile error at the site that must decide, where `asOf: string | null`
 * would have kept working while quietly meaning something else.
 */
/**
 * Tab 07 — Factor Export.
 *
 * FOUR requests, and it is the only tab that makes more than three. That is not a
 * violation of §3's binding table so much as what this tab IS: the board's own build note
 * calls the read side "pure assembly", and the thing being assembled is the four domain
 * states. There is no fifth endpoint and no new analytics — every number here is a number
 * one of the other tabs already prints.
 *
 * Each settles independently, and a domain that fails is NAMED on the page rather than
 * dropped. An export whose coverage silently depends on which engines happened to be up
 * is worse than an incomplete one that says so: the consumer joining it cannot tell a
 * factor that is absent from one that was never asked for.
 *
 * The replay gate is the domain-state one, for the same reason tabs 03/04 use it — these
 * are `/api/macro/*` routes and they select on `as_of`, not `computed_at`. It is driven
 * by the FIRST domain that answered, because the banner speaks for the request and all
 * four were made at one instant; if none answered, `replayVerdictForDomainState` sees no
 * state and the tab's own empty read says so.
 */
async function FactorExportTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : undefined;
  const [inflation, rates, usd, gold] = await Promise.all(
    (["inflation", "rates", "usd", "gold"] as const).map((domain) =>
      settle(() => api.macroDomainState(domain, asOf), `${domain} state API`),
    ),
  );
  const slots: FactorExportSlots = { inflation, rates, usd, gold };
  const answered = [inflation, rates, usd, gold].find((s) => s.value)?.value;

  const verdict = replayVerdictForDomainState(replay, {
    asOf: answered?.as_of,
    computedAt: answered?.computed_at,
    failed: !answered,
  });
  const status = (
    <ReplayStatus
      verdict={verdict}
      publisher="macro factor vector"
      clock="instant"
    />
  );
  if (replayWithholdsContent(verdict)) return status;

  return (
    <>
      {status}
      <div className="board">
        {/* The board's t7 strip is `Q1 Q7`, and here it is also the measured union of the
            three panels below (Q1 on the vector, Q7 on the delivery form and the
            refusal) — so for once the advertised strip and the panels agree exactly. */}
        <BoardSecTitle title="Factor Export" questions={["Q1", "Q7"]}>
          <b>
            Direction contract: equity → reads → macro factor, never the
            reverse.
          </b>{" "}
          The macro desk derives no equity exposure. What it guarantees is that
          the factor is point-in-time correct — available at or before the
          instant asked for, with evidence the desk has since disowned excluded
          by the same clock — and the burden of proving predictive power sits in
          each consumer&apos;s own backtest. That is the only honest division of
          labour once the desk&apos;s own pre-test came back{" "}
          <code>descriptive_only</code>.
        </BoardSecTitle>
        {/* The board's own t7 layout: one `grid g2` with the vector spanning both
            columns, and the two prose panels side by side beneath it. The vector's table
            is five columns wide and does not fit half a column — in a `g2` cell its Type
            column vanished behind the scroller, which is the column carrying the one
            distinction the tab exists to make. */}
        <div className="grid g2">
          <div style={{ gridColumn: "1/-1" }}>
            <FactorVectorPanel slots={slots} />
          </div>
          <DeliveryFormPanel />
          <ExportRefusalPanel />
        </div>
      </div>
    </>
  );
}

/**
 * Tab 06 — Energy · Proposal. The one tab that fetches nothing.
 *
 * It ships as a proposal because the board put it on the desk rather than in a document
 * nobody opens: energy is the supply-side driver of inflation, the denominator of the
 * gold÷oil anchor, and a volatility input on the dollar side — three holes the desk
 * currently cannot see. Every panel is PLANNED except the data inventory, which is a
 * DATED FINDING and says so in its own provenance line.
 *
 * Sync, and it takes the replay prop and ignores it, which is the correct outcome for a
 * tab whose registry entry declares `replayClock: "none"`.
 */
function EnergyTab() {
  return (
    <div className="board">
      <BoardSecTitle title="Energy · Proposal" questions={["Q7"]}>
        <b>Nothing on this tab is ingested yet.</b> Energy is the fifth
        dimension on the chain: the supply-side driver of inflation, the
        denominator of the gold÷oil anchor, and a volatility input on the dollar
        side. The position argued here is narrow —{" "}
        <b>
          feed the inflation node and the gold valuation anchor; becoming a
          fifth domain state requires its own spec and its own measurement
        </b>{" "}
        — and it inherits the desk&apos;s existing non-goals unchanged, making
        no predictive claim about anything.
      </BoardSecTitle>
      <div className="grid g2">
        <EnergyInventoryPanel />
        <EnergyRoutePanel />
        <div style={{ gridColumn: "1/-1" }}>
          <EnergyProposedPanels />
        </div>
      </div>
      <div style={{ marginTop: 12 }}>
        <EnergyDisciplinePanel />
      </div>
    </div>
  );
}

const TAB_CONTENT: Record<MacroTabSlug, MacroTabContent> = {
  // Static prose. It takes the same props as every other tab and ignores them, which is
  // the correct outcome for a tab whose registry entry declares `replayClock: "none"`.
  notes: DesignNotes,
  fed: FedTab,
  rates: CurveTab,
  // Named the way an operator would name them, not by endpoint — the string lands
  // mid-sentence in the replay banner.
  inflation: domainTab("inflation", "inflation state"),
  usd: domainTab("usd", "USD state"),
  gold: GoldTab,
  energy: EnergyTab,
  factors: FactorExportTab,
  overview: OverviewTab,
};

export async function generateMetadata({
  params,
}: {
  params: Promise<{ tab: string }>;
}) {
  const { tab } = await params;
  const entry = VALID_TABS.find((candidate) => candidate.slug === tab);
  return { title: entry ? `Macro · ${entry.label}` : "Macro" };
}

export default async function MacroTabPage({
  params,
  searchParams,
}: {
  params: Promise<{ tab: string }>;
  searchParams: Promise<Record<string, string | string[] | undefined>>;
}) {
  const [{ tab }, query] = await Promise.all([params, searchParams]);
  // The registry is the route guard. An unregistered slug 404s, which is what lets the
  // tab bar grow one entry at a time without ever linking somewhere that does not exist.
  const entry = VALID_TABS.find((candidate) => candidate.slug === tab);
  if (!entry) notFound();

  const replay = parseReplayRequest(query.as_of);
  const Content = TAB_CONTENT[entry.slug];

  return (
    <>
      {/* The REQUEST, stated once above the tab. The tab states the ANSWER below it,
          because only the tab knows what its publishers returned. The clock comes off the
          registry entry so a tab that asks a different question cannot borrow this one's
          label (§10-H). */}
      <ReplayControl
        request={replay}
        clock={entry.replayClock}
        tabHref={macroTabHref(entry.slug)}
        today={todayUtcDate()}
      />
      <Content replay={replay} />
    </>
  );
}
