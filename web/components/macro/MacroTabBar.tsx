"use client";

import Link from "next/link";
import { usePathname, useSearchParams } from "next/navigation";

import { replayHref } from "./replay";
import { macroTabHref, macroTabsForBar } from "./tabs";

/**
 * The macro desk's tab strip.
 *
 * Registry-driven: one link per artifact tab, never a second hardcoded list. The route
 * guard reads the same array, so every visible destination resolves.
 *
 * Two deliberate choices, both of which a copy of an existing bar would get wrong:
 *
 * 1. `prefetch={false}`, not the bare `prefetch` that `components/stock/TabBar.tsx:34`
 *    passes. Bare is `prefetch={true}`, and on a dynamic route that prefetches the FULL
 *    route rather than its loading boundary. This bar grows to nine tabs and sits
 *    entirely in the viewport, so on the stock page's setting every single macro page
 *    view would fire nine full RSC prefetches into `force-dynamic` server components,
 *    each awaiting 1-3 API calls — roughly 20 backend requests per view for the eight
 *    tabs nobody opened. Next's default `'auto'` becomes defensible only once the
 *    per-tab `loading.tsx` is what gets prefetched, and only with a measurement behind
 *    it; ship `false` first.
 *
 * 2. `<nav>` + `aria-current`, not `role="tablist"` + `aria-selected`. The two tablist
 *    models in this repo (`app/cockpit/[ticker]/CockpitTabs.tsx`,
 *    `components/stock/panels/greeks/GreekSubTabs.tsx`) are both `<button>`-based, and
 *    they are honest: their panels are siblings in one document. These tabs are
 *    separate documents reached by navigation, so a tablist role would promise a
 *    widget that does not exist — no panel to own, no arrow-key traversal, no
 *    `aria-controls` that resolves. Honest link markup beats a tablist that lies.
 *
 * 3. Every link CARRIES `?as_of=`. A bare `href` would drop the replay date on the first
 *    tab switch, and the operator would land on a live tab believing he was still
 *    replaying — §3.1's "a replayed tab beside a live one, with nothing on screen saying
 *    so", reintroduced by navigation after P4 fixed it at the API and at the banner. §6
 *    of the plan flagged that propagating it costs `useSearchParams()` and therefore a
 *    Suspense boundary (`app/macro/layout.tsx` supplies one) and multiplies the prefetch
 *    set per distinct date — moot here, because of choice 1.
 *
 *    The value is forwarded VERBATIM, not re-parsed. A rejected `as_of` must keep being
 *    rejected on the next tab: silently dropping it on navigation would turn a visible
 *    refusal into a live page that looks like the replay worked.
 */
export function MacroTabBar() {
  const pathname = usePathname();
  const asOf = useSearchParams().get("as_of");

  return (
    <nav
      className="tabbar"
      aria-label="Macro desk tabs"
      data-testid="macro-tab-bar"
    >
      <div className="wrap">
        <div className="tabs">
          {macroTabsForBar().map((tab) => {
            const href = macroTabHref(tab.slug);
            const active = pathname === href || pathname.startsWith(`${href}/`);
            return (
              <Link
                key={tab.slug}
                href={replayHref(href, asOf)}
                prefetch={false}
                aria-current={active ? "page" : undefined}
                className={`tab${active ? " active" : ""}`}
                data-testid={`macro-tab-${tab.slug}`}
              >
                <span className="n">{tab.ordinal}</span>
                {tab.label}
              </Link>
            );
          })}
        </div>
      </div>
    </nav>
  );
}
