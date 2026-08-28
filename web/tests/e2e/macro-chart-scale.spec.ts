import { expect, test } from "@playwright/test";

/**
 * Invariant 9 — chart scale on the macro desk.
 *
 * `.chart svg { width: 100%; height: auto }` over a fixed `viewBox` stretches the SVG's
 * INTERNAL coordinate system to its container, and `font-size` lives inside that system.
 * So effective type size is `font-size × (container_px ÷ viewBox_width)`. Call that ratio
 * k. The board this desk is ported from renders its SEP dot plot at k = 2.02 and its
 * central-bank strip at k = 0.63 — a 20px label beside a 6px one, on the same page, with
 * both files declaring 10. `components/macro/chartGeometry.ts` already solved this in
 * argon by sizing each frame to the container it actually occupies; this gate is what
 * stops the answer from being lost during the port.
 *
 * §5 of `docs/superpowers/plans/2026-08-27-macro-desk-page-port.md` is the source for the
 * band, the viewport and the numbers quoted below.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * STATUS: LIVE since P3. The `test.fixme` marker P2 shipped is gone — tabs 01/02 brought
 * the charts, so this gate finally has a subject.
 * ─────────────────────────────────────────────────────────────────────────────────────
 *
 * The non-vacuity assertion below (`measurements.length > 0`) was kept rather than
 * softened all through P2, when it could only fail. A gate written as "every SVG we found
 * is in band" passes on an empty set — §7's evaporating-scope defect, the one
 * `web/scripts/lint-gold-copy.mjs` shipped as a silent `continue` over a missing root: a
 * check that reports success precisely when it has stopped checking anything.
 *
 * WHY THE SELECTOR IS `svg[role="img"][viewBox]` AND NOT `svg[viewBox]`.
 *
 * §5 specifies "every `svg` under `/macro/*`", and P2 implemented that literally. Run for
 * the first time in P3, it failed 42 times — on argon's own navigation. The sidebar draws
 * 12 lucide icons on every page, and `/macro/rates` carries 6 more INSIDE `<main>`: each
 * declares `viewBox="0 0 24 24"` and renders at 16px, so k = 0.667. That is not a defect;
 * it is what an icon is. Scoping to `main` does not fix it, because six of them are in
 * there.
 *
 * `role="img"` is not a marker invented for this gate — `web/components/CLAUDE.md` already
 * mandates it on chart SVGs, and all three rates charts carry it (`SepDotPlot.tsx:150`,
 * `RatesCurveChart.tsx:124`, `DealerPathChart.tsx:213`). Measured, it selects exactly the
 * three charts and zero icons.
 *
 * A selector can go blind, so the second assertion below guards it: any SVG in the content
 * area big enough to be a chart must DECLARE itself one. The threshold sits in a real gap
 * — every icon on these routes is 24 units wide and every chart is 760 or 1200, with
 * nothing between — so a new chart that forgets `role="img"` fails loudly instead of
 * being skipped in silence, which is the same defect one level up from the one above.
 *
 * ─────────────────────────────────────────────────────────────────────────────────────
 * FRAME RE-MEASUREMENT — DONE IN P3, at 1440x900, against `npm run start`:
 *
 *   WIDE_FRAME  1200x360 | SEP dot plot   | container 1130px | rendered 1128px | k = 0.940
 *   WIDE_FRAME  1200x360 | dealer path    | container 1130px | rendered 1128px | k = 0.940
 *   NARROW_FRAME 760x300 | yield curve    | container  708.9 | rendered 706.9  | k = 0.930
 *
 * §5 required this because `NARROW_FRAME`'s 760 is cut to a `.curveGrid` cell
 * (`components/rates/RatesDesk.module.css:221`, `minmax(320px, 1.4fr)`) whose width is a
 * FRACTION of the shell — so `app/macro/layout.tsx`'s tab bar could have moved it without
 * moving the number the frame was cut to fit.
 *
 * IT DID NOT. §5 predicted k ≈ 0.94 for `WIDE_FRAME` at 1440px and measured 1132px there
 * before the port; it renders at 1128px after — 0.35%. So the constants are DELIBERATELY
 * UNCHANGED. Pinning `NARROW_FRAME` to today's 708.9 would hard-code one viewport into a
 * module whose whole thesis is that the SCALE FACTOR, not the viewBox, is the invariant.
 * Re-measure again when P4 adds the replay banner — that one adds vertical chrome, but a
 * banner that wraps at a narrow width would take horizontal space too.
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
  test("every /macro/* chart renders at a scale factor near 1", async ({
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

      // A chart in the content area that never declared itself one would be skipped by
      // the selector below without a word. Catch that here rather than let the gate go
      // quietly blind: 200 units sits in the empty gap between every icon on these
      // routes (24) and every chart (760, 1200).
      const undeclared = await page.$$eval(
        "main svg[viewBox]:not([role='img'])",
        (nodes) =>
          nodes
            .map((node) => node.getAttribute("viewBox") ?? "")
            .filter(
              (viewBox) => Number(viewBox.trim().split(/[\s,]+/)[2]) >= 200,
            ),
      );
      expect(
        undeclared,
        `${route}: an SVG at least 200 units wide sits in <main> without role="img", so ` +
          `this gate would skip it. web/components/CLAUDE.md requires role="img" on ` +
          `chart SVGs; add it, or this chart's scale goes unchecked forever.`,
      ).toEqual([]);

      // Only SVGs that DECLARE a viewBox are in scope: an SVG without one is not
      // stretching a coordinate system, so it has no scale factor to hold. Hidden and
      // zero-width SVGs are deliberately NOT filtered out — a chart that renders at 0px
      // is a defect this gate should surface, not one it should excuse away.
      const found = await page.$$eval('svg[role="img"][viewBox]', (nodes) =>
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
