import { expect, test } from "@playwright/test";

/**
 * Invariant 9 — chart scale on the macro desk.
 *
 * `.chart svg { width: 100%; height: auto }` over a fixed `viewBox` stretches the SVG's
 * INTERNAL coordinate system to its container, and `font-size` lives inside that system.
 * So effective type size is `font-size × (container_px ÷ viewBox_width)`. Call that ratio
 * k. The board this desk is ported from renders its SEP dot plot at k = 2.02 and its
 * central-bank strip at k = 0.63 — a 20px label beside a 6px one, on the same page, with
 * both files declaring 10. `components/rates/chartGeometry.ts` already solved this in
 * argon by sizing each frame to the container it actually occupies; this gate is what
 * stops the answer from being lost during the port.
 *
 * §5 of `docs/superpowers/plans/2026-08-27-macro-desk-page-port.md` is the source for the
 * band, the viewport and the numbers quoted below.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * STATUS: `test.fixme` — declared, not run. **P3 deletes the marker.**
 * ─────────────────────────────────────────────────────────────────────────────────────
 *
 * P2 registers exactly one tab (08, Design Notes), and it is prose: there are currently
 * zero `<svg>` elements anywhere under `app/macro/` or `components/macro/`. The assertion
 * that this gate found AT LEAST ONE SVG therefore fails today, by construction and on
 * purpose.
 *
 * That assertion is kept rather than softened, and the distinction matters more than it
 * looks. A gate written as "every SVG we found is in band" passes on an empty set — which
 * is §7's evaporating-scope defect, the one `web/scripts/lint-gold-copy.mjs` shipped as a
 * silent `continue` over a missing root: a check that reports success precisely when it
 * has stopped checking anything. Softening the count assertion would make this file green
 * in P2 and green forever after, including on the day someone deletes every chart. So the
 * body below is written exactly as it will run, and the marker — not the assertion —
 * carries the fact that its subject has not arrived yet.
 *
 * **P3 (`feat/macro-desk-tabs-01-02`) is the PR that removes the `fixme`.** P3 re-homes
 * the rates desk under tabs 01/02, which is where the SVGs arrive; from that commit on,
 * this gate has a non-empty subject and must be green. Changing `test.fixme` back to
 * `test` is a one-word edit and belongs in that same commit.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * ALSO OWED BY P3, recorded here so it is not lost with the marker (§5, last paragraph):
 *
 *   `chartGeometry.ts`'s `WIDE_FRAME` (1200) and `NARROW_FRAME` (760) widths must be
 *   RE-MEASURED IN A REAL BROWSER once the shell's tab bar is in place and before the
 *   charts arrive. They are not constants across this port. `NARROW_FRAME`'s 760 is sized
 *   to a `.curveGrid` cell (`components/rates/RatesDesk.module.css:288`, `minmax(320px,
 *   1.4fr)`) whose width is a FRACTION of the shell — so adding `app/macro/layout.tsx`'s
 *   tab bar, and later P4's replay banner, changes the container without changing the
 *   number the frame was cut to fit. A frame left at a stale width is precisely the
 *   defect this gate detects, which means the port can break the gate the port
 *   introduces. Re-measure, then update `chartGeometry.ts` if they moved.
 * ─────────────────────────────────────────────────────────────────────────────────────
 */

// The viewport is PART OF THE GATE, not an incidental of the runner.
//
// k is `container_px ÷ viewBox_width`, and `container_px` moves with the viewport: the
// same `WIDE_FRAME` chart lands at k ≈ 0.94 in a 1440px viewport and k ≈ 1.00 in a 1512px
// one (`chartGeometry.ts:17-18` states its frames were measured at 1512px; §5's table was
// measured at 1440px, where a 1200-unit viewBox renders at ~1132px). A gate that does not
// pin its viewport measures whatever the runner happened to default to, and the band's
// width silently becomes an artifact of a number nobody wrote down. 1440 is the width the
// band below was justified against, so 1440 is what this file asks for.
test.use({ viewport: { width: 1440, height: 900 } });

// Why ±10% and not tighter, AT 1440px. A tighter [0.95, 1.06] would fail the very charts
// being ported: argon's rates strips declare a 1200-unit viewBox and render at ~1132px,
// i.e. k ≈ 0.94, and they are correct. The band has to admit the existing, correct charts
// while still catching the real defects — the board's k = 2.02 and k = 0.63 are both far
// outside any sane band, so nothing is lost by being generous here. Tighten later,
// per-family, if the desk's frames converge.
const K_MIN = 0.9;
const K_MAX = 1.1;

type Measurement = {
  route: string;
  label: string;
  viewBox: string;
  viewBoxWidth: number;
  renderedWidth: number;
};

test.describe("macro desk — chart scale", () => {
  test.fixme("every /macro/* SVG renders at a scale factor near 1", async ({
    page,
  }) => {
    // The routes to sweep are read from the tab bar rather than hardcoded, for the same
    // reason the registry drives the bar: a tab added in a later PR is swept the moment
    // it is registered, with no second list to keep in step. `/macro` is included
    // because the desk's own landing page is under the shell too and draws into the
    // same container.
    await page.goto("/macro/notes");
    await page.waitForLoadState("networkidle");
    const tabHrefs = await page
      .locator('[data-testid="macro-tab-bar"] a')
      .evaluateAll((nodes) =>
        nodes.map((node) => node.getAttribute("href") ?? ""),
      );
    expect(tabHrefs.length).toBeGreaterThan(0);
    const routes = ["/macro", ...tabHrefs];

    const measurements: Measurement[] = [];
    for (const route of routes) {
      await page.goto(route);
      await page.waitForLoadState("networkidle");

      // Only SVGs that DECLARE a viewBox are in scope: an SVG without one is not
      // stretching a coordinate system, so it has no scale factor to hold. Hidden and
      // zero-width SVGs are deliberately NOT filtered out — a chart that renders at 0px
      // is a defect this gate should surface, not one it should excuse away.
      const found = await page.$$eval("svg[viewBox]", (nodes) =>
        nodes.map((node) => {
          const viewBox = node.getAttribute("viewBox") ?? "";
          const parts = viewBox
            .trim()
            .split(/[\s,]+/)
            .map(Number);
          return {
            label:
              node.getAttribute("data-testid") ??
              node.querySelector("title")?.textContent?.trim() ??
              node.getAttribute("aria-label") ??
              "(unlabelled svg)",
            viewBox,
            // A viewBox is `min-x min-y width height`; width is the third value.
            viewBoxWidth: parts.length === 4 ? parts[2] : Number.NaN,
            renderedWidth: node.getBoundingClientRect().width,
          };
        }),
      );
      measurements.push(...found.map((m) => ({ ...m, route })));
    }

    // THE NON-VACUITY ASSERTION. See the STATUS block above before touching it: this is
    // what makes the gate fail on an empty set instead of passing on one.
    expect(
      measurements.length,
      "no /macro/* SVG declares a viewBox — this gate has no subject, which is a " +
        "failure, not a pass",
    ).toBeGreaterThan(0);

    for (const m of measurements) {
      expect(
        Number.isFinite(m.viewBoxWidth) && m.viewBoxWidth > 0,
        `${m.route} ${m.label}: malformed viewBox "${m.viewBox}"`,
      ).toBe(true);

      const k = m.renderedWidth / m.viewBoxWidth;
      expect(
        k,
        `${m.route} ${m.label}: k=${k.toFixed(3)} ` +
          `(${m.renderedWidth.toFixed(1)}px rendered / ${m.viewBoxWidth} viewBox units) ` +
          `— text declared at 10 renders at ${(10 * k).toFixed(1)}px. ` +
          `Pick the chartGeometry.ts frame whose width matches this container; ` +
          `do not compensate with font-size.`,
      ).toBeGreaterThanOrEqual(K_MIN);
      expect(k).toBeLessThanOrEqual(K_MAX);
    }
  });
});
