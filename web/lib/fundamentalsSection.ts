/**
 * The desk's section identity and its URL<->chain mapping.
 *
 * These live outside the page modules because Next validates a page's export
 * surface: a route file may export only Next's own known symbols (`default`,
 * `dynamic`, `metadata`, …), and anything else is a type error. The failure is
 * easy to miss — the check reads generated files under `.next/dev/types/`,
 * which only exist for routes a dev server has actually built, so `tsc
 * --noEmit` passes on a clean tree and starts failing after someone runs
 * `next dev`.
 */

/** The one section registered today. A section is a registry row on the API
 *  side (`SECTIONS` in `api/routers/fundamentals_desk.py`); this is the web
 *  side's name for it. */
export const SECTION = "ai-semi";

/**
 * Rejoin a catch-all route's segments into a chain name.
 *
 * The route is a CATCH-ALL because 20 of the desk's 38 chain names contain a
 * slash (`Networking/Optical`, `Semi-Logic/ASIC`, `Cooling/Thermal`, …) and a
 * single dynamic segment cannot match one. Next hands the segments already
 * decoded, so rejoining with "/" recovers the name exactly, and a chain
 * WITHOUT a slash arrives as a one-element array and resolves the same way.
 */
export function chainFromSegments(segments: string[]): string {
  return segments.join("/");
}
