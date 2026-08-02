/**
 * Which cone horizons may be drawn on a time axis that already ends at `lastBarDate`.
 *
 * Lives outside DensityConeChart so it can be tested without a canvas: lightweight-charts
 * pulls in fancy-canvas, which needs `window.matchMedia` and therefore cannot be rendered
 * under vitest (see web/CLAUDE.md).
 *
 * Two rules, both about not drawing a claim the data does not support:
 *   - a target date at or before the last real bar is dropped, because the fan would be
 *     painted over a session whose outcome is already known;
 *   - equal or out-of-order dates are dropped, because lightweight-charts requires
 *     strictly ascending times and only its DEVELOPMENT bundle asserts on it — in
 *     production a duplicate silently renders a degenerate series instead of failing.
 *
 * Duplicates are reachable, not theoretical: the nightly settle rewrites target_date to
 * the actual H-th trading day while unsettled horizons keep a plain weekday estimate, so
 * a market holiday inside the window lets a settled h=N collide with h=N+1's estimate.
 */
export function drawableRows<T extends { target_date: string }>(
  rows: T[],
  lastBarDate: string,
): T[] {
  let prev = lastBarDate;
  return rows.filter((r) => {
    if (r.target_date <= prev) return false;
    prev = r.target_date;
    return true;
  });
}
