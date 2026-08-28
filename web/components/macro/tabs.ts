/**
 * The macro desk's tab registry.
 *
 * This is a REGISTRY, not a schedule. The difference is the whole point.
 *
 * A schedule would list all nine board tabs up front and let each PR fill one in. The
 * bar would then render nine links from day one, of which eight resolve to a route that
 * does not exist — eight 404s reachable from every macro page for the length of six PRs.
 *
 * Instead, one list feeds both halves of the navigation:
 *
 *   - `app/macro/[tab]/page.tsx` calls `notFound()` on any slug not registered here;
 *   - `<MacroTabBar/>` renders exactly one link per entry, never a hardcoded list.
 *
 * Because both read the same array, the bar cannot link to a route that 404s and the
 * route cannot answer a slug the bar does not show. A tab becomes reachable in the same
 * commit that makes it real, and not before.
 *
 * How to add one: append an entry here IN THE SAME COMMIT that adds its content to
 * `TAB_CONTENT` in `app/macro/[tab]/page.tsx`. That map is typed by `MacroTabSlug`,
 * which is derived from this array, so registering a tab with nothing behind it is a
 * compile error rather than a runtime 404.
 *
 * P2 seeds this with tab 08 (Design Notes) alone — static prose, no data path. That tab
 * has since been marked `audience: "operator"`: it is registered and reachable by URL,
 * and it is not in the strip, because the board says it does not ship on the final page.
 */

import type { ReactElement } from "react";

import type { MacroReplayClock, MacroReplayRequest } from "./replay";

export type MacroTabEntry = {
  /** URL segment. The tab lives at `/macro/{slug}`. */
  slug: string;
  /**
   * The board's own two-digit tab number, zero-padded.
   *
   * Kept as data rather than implied by array position, because registration order is
   * PR order and PR order is not board order: tabs 01/02 register before tab 00, and
   * 03-05 after it. The bar sorts on this, so an entry appended at the end still lands
   * in its board slot.
   */
  ordinal: string;
  /** Tab-bar label. Rendered uppercase by `.ticker-tab`. */
  label: string;
  /**
   * WHICH QUESTION this tab's `as_of` control asks. Required, with no default.
   *
   * §3.1 of the plan banned a single desk-wide picker over all five domain tabs until
   * the gold clock was settled, because `/api/gold/replay` keys on `obs_date` with exact
   * equality while `/api/rates/snapshot` keys on `computed_at` and `/api/macro/*` on an
   * instant. §10-H settled it — label it, do not change the API — and this field is that
   * label. It has no default precisely so tab 05 cannot inherit tab 02's question by
   * omission: registering a tab without naming its clock does not compile.
   *
   * It must name what the tab's endpoint ACTUALLY keys on. A tab that declares `instant`
   * while calling an `obs_date` route is the failure §3.1 describes, wearing a label.
   */
  replayClock: MacroReplayClock;
  /**
   * Who the tab is FOR. Optional, defaulting to the desk, because the desk is what a tab
   * is for unless the board says otherwise — and it says so exactly once.
   *
   * `"operator"` keeps the route registered and reachable by URL while removing it from
   * the strip. The board's t8 opens with the instruction: _"This tab is for you (the
   * operator) and does not ship on the final page."_ Deleting the entry instead would
   * satisfy the letter of that and lose the tab entirely; leaving it in the bar was the
   * shipped state and ignored it.
   *
   * This does NOT weaken the registry invariant. The bar renders a SUBSET of the
   * registry, so it still cannot link anywhere that fails to resolve — only fewer places.
   * The route guard keeps reading the full array, which is what keeps the URL alive.
   */
  audience?: "desk" | "operator";
};

export const VALID_TABS = [
  {
    slug: "notes",
    ordinal: "08",
    label: "Design Notes",
    replayClock: "none",
    audience: "operator",
  },
  { slug: "fed", ordinal: "01", label: "Fed · Policy", replayClock: "instant" },
  {
    slug: "rates",
    ordinal: "02",
    label: "Rates · Curve",
    replayClock: "instant",
  },
  // Tabs 03 and 04 read `/api/macro/{inflation,usd}`, which `resolve_instant` resolves the
  // same way `/api/rates/snapshot` does. The COLUMN each filters on differs — `as_of` here
  // against `computed_at` there (`macro_domain_state.py:222` vs `rates_repository.py:205`)
  // — but the operator's question is the same one, "what did the desk know at T", and that
  // is what this field names. `replayVerdictForDomainState` is where the column difference
  // is honoured.
  {
    slug: "inflation",
    ordinal: "03",
    label: "Inflation",
    replayClock: "instant",
  },
  { slug: "usd", ordinal: "04", label: "US Dollar", replayClock: "instant" },
  // THE obs_date TAB, and the reason this field exists at all. `/api/gold/replay` is
  // `WHERE obs_date = %s` — exact equality on the market day the reading is ABOUT, not an
  // at-or-before on when the desk knew it (`storage/gold.py`, via `routers/gold.py`).
  // §10-H settled it as a labelling decision rather than an API change, and this line is
  // the label. Declaring `"instant"` here would be §3.1's failure wearing a badge: the
  // type system cannot check that a tab's declared clock matches what its endpoint keys
  // on, so this is the one entry a reviewer must read against the router.
  { slug: "gold", ordinal: "05", label: "Gold", replayClock: "obs_date" },
] as const satisfies readonly MacroTabEntry[];

/** The registered slugs, as a literal union. `TAB_CONTENT` is keyed by this. */
export type MacroTabSlug = (typeof VALID_TABS)[number]["slug"];

/**
 * What every tab's content component is handed. See the block above `TAB_CONTENT` in
 * `app/macro/[tab]/page.tsx` for why it is a props object carrying the REQUEST rather
 * than a resolved instant, pre-fetched data, or a bare `asOf` string.
 */
export type MacroTabProps = { replay: MacroReplayRequest };

/** The value type of `TAB_CONTENT`. A tab may be sync (static prose) or async (it awaits
 *  its own publishers on the server); both are components, instantiated as JSX. */
export type MacroTabContent = (
  props: MacroTabProps,
) => ReactElement | Promise<ReactElement>;

/** One place that knows the URL shape, so the bar and any test agree on it. */
export function macroTabHref(slug: string): string {
  return `/macro/${slug}`;
}

/** Board order. Zero-padded two-digit strings sort lexicographically as numbers. */
export function macroTabsInBoardOrder(): readonly MacroTabEntry[] {
  return [...VALID_TABS].sort((a, b) => a.ordinal.localeCompare(b.ordinal));
}

/**
 * What the tab strip shows: board order, minus the operator-only tabs.
 *
 * Kept apart from `macroTabsInBoardOrder` rather than filtering in place, because the two
 * questions are different and one of them is the route guard's. Anything that asks "which
 * tabs exist" must keep getting all of them.
 */
export function macroTabsForBar(): readonly MacroTabEntry[] {
  return macroTabsInBoardOrder().filter((tab) => tab.audience !== "operator");
}
