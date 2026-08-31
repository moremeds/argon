import { expect, test } from "@playwright/test";

/**
 * `/gold` → `/macro/gold`. Modelled on `rates-redirect.spec.ts`, which owns the same
 * contract for `/rates`.
 *
 * Three assertions, and the third is the one this desk needs that the rates redirect did
 * not:
 *
 *  1. A browser navigation to `/gold` ends up on `/macro/gold` — the user-visible outcome.
 *  2. The redirect Next.js emits is a **308**. `maxRedirects: 0` is what makes the test
 *     able to tell the difference: a plain `page.goto` follows the hop transparently and
 *     cannot distinguish a 308 from a 302 or a `router.replace()` in a `useEffect`. The
 *     plan calls this out by name — once `/gold` redirects, backing it out needs a second
 *     deploy, so the status code is the part worth pinning.
 *  3. **`/gold/replay/<date>` still answers.** The replay route remains public, and the redirect is
 *     written `source: "/gold"` — the EXACT path — precisely so a `/gold/:path*` wildcard
 *     cannot swallow it. That is a one-character difference in a config file with no
 *     visible symptom until somebody follows a deep link, which is exactly the kind of
 *     thing that needs a test rather than a comment.
 */

test.describe("/gold redirect", () => {
  test("navigating to /gold lands on the macro desk's gold tab", async ({
    page,
  }) => {
    await page.goto("/gold");
    await page.waitForLoadState("networkidle");

    expect(page.url()).toMatch(/\/macro\/gold$/);
    // ...inside the desk, not on some other page that happens to answer there.
    await expect(page.getByTestId("macro-tab-bar")).toBeVisible();
  });

  test("the redirect is a permanent 308, not a 307 or a client-side bounce", async ({
    page,
  }) => {
    const response = await page.request.get("/gold", { maxRedirects: 0 });

    expect(response.status()).toBe(308);
    expect(response.headers()["location"]).toBe("/macro/gold");
  });

  test("the kept replay route is NOT swallowed by the redirect", async ({
    page,
  }) => {
    const response = await page.request.get("/gold/replay/2026-08-14", {
      maxRedirects: 0,
    });

    // Whatever it renders — a posture, "no row for that date", or a failed request — it
    // must not be a redirect. A `/gold/:path*` source would make this a 308 to
    // `/macro/gold/replay/2026-08-14`, which is not a route.
    expect(response.status()).not.toBe(308);
    expect(response.status()).not.toBe(307);
  });
});
