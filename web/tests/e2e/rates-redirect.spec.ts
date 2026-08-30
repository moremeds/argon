import { expect, test } from "@playwright/test";

/**
 * `/rates` → `/macro/rates`: the rates desk is retired into the macro desk's curve tab,
 * and the old URL must
 * keep working as a **permanent** redirect rather than quietly 404ing.
 *
 * Two assertions, deliberately split:
 *
 *  1. A browser navigation to `/rates` ends up on `/macro/rates` — the user-visible outcome.
 *  2. The redirect Next.js actually emits is a **308**, not a 307 or a client-side bounce.
 *     `maxRedirects: 0` is what makes this test able to tell the difference — a normal
 *     `page.goto("/rates")` follows the redirect transparently and can't distinguish a
 *     308 from a 302 or a `router.replace()` in a `useEffect`. The plan calls this out by
 *     name: once `/rates` redirects, backing it out needs a second deploy, so the status
 *     code — not just the landing URL — is the part worth pinning here.
 *
 * Deliberately NOT here: anything about what `/macro/rates` renders. That tab is built in
 * this same PR by a different pass of work; this spec only owns the redirect.
 */

test.describe("/rates redirect", () => {
  test("navigating to /rates lands on /macro/rates", async ({ page }) => {
    await page.goto("/rates");
    await page.waitForLoadState("networkidle");

    expect(page.url()).toMatch(/\/macro\/rates$/);
  });

  test("the redirect is a permanent 308, not a 307 or a client-side bounce", async ({
    page,
  }) => {
    const response = await page.request.get("/rates", { maxRedirects: 0 });

    expect(response.status()).toBe(308);
    expect(response.headers()["location"]).toBe("/macro/rates");
  });
});
