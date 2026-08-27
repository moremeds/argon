import { notFound } from "next/navigation";

import { DesignNotes } from "@/components/macro/DesignNotes";
import { VALID_TABS, type MacroTabSlug } from "@/components/macro/tabs";

// Per-route rather than per-page-load: the tabs that arrive in later PRs each read
// 1-3 live endpoints, and P4 adds an `as_of` searchParam that must re-fetch on the
// server. Declared here now so no tab ever inherits a cached shell by accident.
export const dynamic = "force-dynamic";

/**
 * Registered slug -> its content.
 *
 * Keyed by `MacroTabSlug`, which is derived from `VALID_TABS` itself, so this map and
 * the registry cannot drift: adding a tab to the registry without adding its content
 * here fails typecheck rather than 404ing at runtime.
 */
const TAB_CONTENT: Record<MacroTabSlug, () => React.ReactElement> = {
  notes: DesignNotes,
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
