import { notFound } from "next/navigation";

import { DesignNotes } from "@/components/macro/DesignNotes";
import { DomainStateTab } from "@/components/macro/DomainStateTab";
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
  const [snapshot, policy] = await Promise.all([
    settle(() => api.ratesSnapshot(asOf), "rates API"),
    settle(() => api.macroPolicy(asOf), "macro policy API"),
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
      />
    </>
  );
}

/** Tab 02 — Rates · Curve. One publisher: everything this tab renders comes out of the
 *  one rates snapshot, so there is nothing here to settle against a second clock — and
 *  nothing to disagree with the replay banner either. */
async function CurveTab({ replay }: MacroTabProps) {
  const asOf = replay.kind === "replay" ? replay.asOf : undefined;
  const snapshot = await settle(() => api.ratesSnapshot(asOf), "rates API");

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
      <CurveDesk snapshot={snapshot.value} errorMessage={snapshot.error} />
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
    const state = await settle(
      () => api.macroDomainState(domain, asOf),
      `${domain} state API`,
    );

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
        <DomainStateTab domain={domain} slot={slot} />
      </>
    );
  };
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
