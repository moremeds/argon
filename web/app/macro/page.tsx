import { redirect } from "next/navigation";

/**
 * `/macro` is the desk, and the desk's front door is tab 00.
 *
 * Until P5 this file WAS the four-domain-card page, and §8 of the port plan required it
 * left alone precisely so `/macro` never 404'd while the registry grew from one tab to
 * nine. Tab 00 is what makes the redirect safe: `/macro/overview` is registered in
 * `VALID_TABS` in the same commit as this flip, so there is no window in which the desk's
 * own root points at a route that does not exist.
 *
 * NOTHING IS ORPHANED BY THE FLIP. The four cards, their per-domain chain flags and the
 * chain verdict all moved to `components/macro/OverviewDesk.tsx`, which tab 00 renders —
 * with more around them, not less. `MacroDesk.tsx`, which was this page's shell (its own
 * `<h1>`, gutter and max-width), is retired rather than moved: a page shell for a page
 * that no longer exists is a second assembly of the same four cards, and two assemblies
 * drift.
 *
 * `redirect()` inside a Server Component issues a 307. That is correct here and a 308
 * would not be: this is a temporary destination in the sense that matters — a caller
 * should keep asking `/macro` for "the macro desk" rather than caching `overview` as its
 * permanent identity. The permanent 308s on this desk are the ones that retire a page's
 * URL entirely (`/rates` in P3, `/gold` in P6), and they live in `next.config.mjs`.
 */
export default function MacroPage() {
  redirect("/macro/overview");
}
