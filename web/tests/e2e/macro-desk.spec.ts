import { expect, test, type Page } from "@playwright/test";

/**
 * The macro desk shell, in a real browser.
 *
 * This file closes the gap §9 of `docs/superpowers/plans/2026-08-27-macro-desk-page-port.md`
 * recorded: sweeping every `page.goto(` under `web/tests/e2e/` found NO spec that
 * navigates to `/macro`. The closest were `/rates` and `/gold`, and only API requests
 * reached `/api/macro/*` — so the desk's own routes had no browser coverage at all while
 * the port was about to start moving them.
 *
 * What it holds, in order of how expensive the regression would be:
 *
 *  1. The registry identity at the HTTP level. `tests/unit/macroTabBar.test.tsx` already
 *     asserts it at the RENDER level — one link per `VALID_TABS` entry and nothing else.
 *     That test cannot know whether those hrefs resolve, because it never leaves jsdom.
 *     This one navigates each rendered link and checks the route exists. §8's rule is
 *     "no PR may ship a link to a route that does not exist"; a render-level assertion
 *     proves the bar and the registry agree, and only a navigation proves the registry
 *     and the router agree.
 *  2. The route guard's other direction — an unregistered slug 404s rather than
 *     rendering an empty shell.
 *  3. `/macro` itself still renders the four domain cards. This is the one that looks
 *     redundant and is not: §8 requires `app/macro/page.tsx` be left ALONE until P5,
 *     precisely so `/macro` never 404s while the bar grows from one tab to nine. That
 *     requirement is a comment in a plan until a test fails when someone flips the page
 *     to `redirect("/macro/overview")` early.
 *
 * Deliberately NOT here: `/rates` and `/gold`. Their 308s ride P3 and P6 with their
 * destinations, so re-pointing `macro-rates-state.spec.ts` / `gold-page.spec.ts` belongs
 * to those PRs, not this one.
 */

/** Console-error collector, matching `gold-page.spec.ts:10-13` and `:44`. */
function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}

/** The favicon 404 is chrome noise, not the page's doing — same filter as `gold-page.spec.ts:44`. */
function realErrors(errors: string[]): string[] {
  return errors.filter((message) => !/favicon/i.test(message));
}

test.describe("macro desk shell", () => {
  test("tab 08 renders under the desk's tab bar", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    const response = await page.goto("/macro/notes");
    expect(response?.status()).toBe(200);
    await page.waitForLoadState("networkidle");

    // The tab's own content, by the testid `DesignNotes` carries.
    await expect(page.getByTestId("macro-design-notes")).toBeVisible();
    await expect(
      page.getByRole("heading", { name: "Design Notes", level: 1 }),
    ).toBeVisible();

    // The shell around it. The bar lives in `app/macro/layout.tsx`, so its absence here
    // would mean the tab rendered outside the desk rather than inside it.
    await expect(page.getByTestId("macro-tab-bar")).toBeVisible();
    await expect(page.getByTestId("macro-tab-notes")).toHaveAttribute(
      "aria-current",
      "page",
    );

    expect(realErrors(consoleErrors)).toEqual([]);
  });

  test("every link the tab bar renders resolves to a route that exists", async ({
    page,
  }) => {
    await page.goto("/macro/notes");
    await page.waitForLoadState("networkidle");

    const links = page.locator('[data-testid="macro-tab-bar"] a');
    const hrefs = await links.evaluateAll((nodes) =>
      nodes.map((node) => node.getAttribute("href") ?? ""),
    );

    // A bar that rendered nothing would make every assertion below vacuously true, and
    // this spec would then "pass" through the exact outage it exists to catch.
    expect(hrefs.length).toBeGreaterThan(0);
    expect(hrefs).toContain("/macro/notes");
    for (const href of hrefs) {
      expect(href).toMatch(/^\/macro\/[^/]+$/);
    }

    for (const href of hrefs) {
      const response = await page.goto(href);
      expect(
        response,
        `${href} produced no response — the bar links somewhere unreachable`,
      ).not.toBeNull();
      // Asserted as "not 404" rather than "is 200" on purpose: later tabs fetch 1-3 live
      // endpoints each, and a dead publisher must be allowed to cost that tab its data
      // without failing THIS gate, which is about the route existing. A 404 is the one
      // status that means the registry and the router disagree.
      expect(
        response?.status(),
        `${href} is linked from the tab bar but 404s`,
      ).not.toBe(404);

      // ...and it landed inside the desk, not on some other page that happens to answer.
      await expect(page.getByTestId("macro-tab-bar")).toBeVisible();
    }
  });

  test("a slug the registry does not know is a 404, not an empty shell", async ({
    page,
  }) => {
    const response = await page.goto("/macro/definitely-not-a-tab");

    // `app/macro/[tab]/page.tsx` calls `notFound()` on any slug absent from `VALID_TABS`.
    // Without this, an unregistered tab would render the layout with a blank body and
    // read as a broken page rather than a missing one.
    expect(response?.status()).toBe(404);
    await expect(page.getByTestId("macro-design-notes")).toHaveCount(0);
  });

  test("/macro still renders the four domain cards", async ({ page }) => {
    const consoleErrors = collectConsoleErrors(page);

    // §8: `app/macro/page.tsx` is left alone until P5, so `/macro` never 404s while the
    // registry grows from one tab to nine. P5 is the PR that may replace this with
    // `redirect("/macro/overview")` — and it must do so in the commit that registers tab
    // 00, which is what this assertion is here to force.
    const response = await page.goto("/macro");
    expect(response?.status()).toBe(200);
    await page.waitForLoadState("networkidle");

    for (const domain of ["inflation", "policy_rates", "usd", "gold"]) {
      await expect(page.getByTestId(`macro-domain-${domain}`)).toBeVisible();
    }

    // The shell wraps `/macro` too (the layout sits above both the page and `[tab]`),
    // and no tab is current here because `/macro` is not itself a registered tab.
    const bar = page.getByTestId("macro-tab-bar");
    await expect(bar).toBeVisible();
    await expect(bar.locator("[aria-current]")).toHaveCount(0);

    expect(realErrors(consoleErrors)).toEqual([]);
  });
});
