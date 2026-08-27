"use client";

import Link from "next/link";
import { usePathname } from "next/navigation";

import { macroTabHref, macroTabsInBoardOrder } from "./tabs";

/**
 * The macro desk's tab strip.
 *
 * Registry-driven: one link per `VALID_TABS` entry, never a hardcoded list. The route
 * guard reads the same array, so this bar can only ever link somewhere that resolves.
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
 */
export function MacroTabBar() {
  const pathname = usePathname();

  return (
    <nav
      className="ticker-tabs macro-tabs"
      aria-label="Macro desk tabs"
      data-testid="macro-tab-bar"
    >
      {macroTabsInBoardOrder().map((tab) => {
        const href = macroTabHref(tab.slug);
        // Prefix match as well as equality so a tab that later grows a child route
        // (the gold replay surface is the named candidate) still highlights its own tab
        // rather than none.
        const active = pathname === href || pathname.startsWith(`${href}/`);
        return (
          <Link
            key={tab.slug}
            href={href}
            prefetch={false}
            aria-current={active ? "page" : undefined}
            className={`ticker-tab macro-tab${active ? " active" : ""}`}
            data-testid={`macro-tab-${tab.slug}`}
          >
            {tab.label}
          </Link>
        );
      })}
    </nav>
  );
}
