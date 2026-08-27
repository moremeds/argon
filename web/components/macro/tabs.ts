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
 * P2 seeds this with tab 08 (Design Notes) alone — static prose, no data path.
 */

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
};

export const VALID_TABS = [
  { slug: "notes", ordinal: "08", label: "Design Notes" },
] as const satisfies readonly MacroTabEntry[];

/** The registered slugs, as a literal union. `TAB_CONTENT` is keyed by this. */
export type MacroTabSlug = (typeof VALID_TABS)[number]["slug"];

/** One place that knows the URL shape, so the bar and any test agree on it. */
export function macroTabHref(slug: string): string {
  return `/macro/${slug}`;
}

/** Board order. Zero-padded two-digit strings sort lexicographically as numbers. */
export function macroTabsInBoardOrder(): readonly MacroTabEntry[] {
  return [...VALID_TABS].sort((a, b) => a.ordinal.localeCompare(b.ordinal));
}
