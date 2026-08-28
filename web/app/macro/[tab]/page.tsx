import { notFound } from "next/navigation";

import { DesignNotes } from "@/components/macro/DesignNotes";
import { VALID_TABS, type MacroTabSlug } from "@/components/macro/tabs";
import { CurveDesk } from "@/components/rates/CurveDesk";
import { FedDesk } from "@/components/rates/FedDesk";
import { settle } from "@/components/rates/deskShared";
import { api } from "@/lib/api";

// Per-route rather than per-page-load: the tabs that arrive in later PRs each read
// 1-3 live endpoints, and P4 adds an `as_of` searchParam that must re-fetch on the
// server. Declared here now so no tab ever inherits a cached shell by accident.
export const dynamic = "force-dynamic";

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
 */
async function FedTab() {
  const [snapshot, policy] = await Promise.all([
    settle(() => api.ratesSnapshot(), "rates API"),
    settle(() => api.macroPolicy(), "macro policy API"),
  ]);

  return (
    <FedDesk
      snapshot={snapshot.value}
      errorMessage={snapshot.error}
      policyComparison={policy.value}
      policyComparisonError={policy.error}
    />
  );
}

/** Tab 02 — Rates · Curve. One publisher: everything this tab renders comes out of the
 *  one rates snapshot, so there is nothing here to settle against a second clock. */
async function CurveTab() {
  const snapshot = await settle(() => api.ratesSnapshot(), "rates API");

  return <CurveDesk snapshot={snapshot.value} errorMessage={snapshot.error} />;
}

/**
 * Registered slug -> its content.
 *
 * Keyed by `MacroTabSlug`, which is derived from `VALID_TABS` itself, so this map and
 * the registry cannot drift: adding a tab to the registry without adding its content
 * here fails typecheck rather than 404ing at runtime.
 *
 * The value type admits an async component as well as a synchronous one. Tabs 01 and 02
 * await their own publishers on the server, and a `() => React.ReactElement` signature
 * would have forced their fetches up into this page — one shared fetch for two tabs that
 * do not need the same data.
 */
const TAB_CONTENT: Record<
  MacroTabSlug,
  () => React.ReactElement | Promise<React.ReactElement>
> = {
  notes: DesignNotes,
  fed: FedTab,
  rates: CurveTab,
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
}: {
  params: Promise<{ tab: string }>;
}) {
  const { tab } = await params;
  // The registry is the route guard. An unregistered slug 404s, which is what lets the
  // tab bar grow one entry at a time without ever linking somewhere that does not exist.
  const entry = VALID_TABS.find((candidate) => candidate.slug === tab);
  if (!entry) notFound();

  const Content = TAB_CONTENT[entry.slug];
  return <Content />;
}
