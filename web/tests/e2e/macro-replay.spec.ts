import { expect, test, type Page } from "@playwright/test";

/**
 * Point-in-time replay on the macro desk, in a real browser against the real API.
 *
 * `web/tests/e2e/macro-rates-state.spec.ts`'s three replay tests are the model one layer
 * down: they exercise `/api/macro/rates` directly through the Next rewrite. These
 * exercise the SURFACE — the searchParam, the control, and the banner — which is the half
 * §8 of the port plan said had been recommended and never scheduled: "Recommending a
 * capability and never scheduling its UI is how a backend parameter ships dead."
 *
 * Written to hold in EVERY data state this environment can be in, matching the discipline
 * of `macro-rates-state.spec.ts`. That is why the replay assertions use 2000-01-01: no
 * rates snapshot can predate it, so "the desk withholds and says why" is deterministic
 * whether or not the local database has ever computed one. A test that skipped itself on
 * an empty database would skip the failure it exists to catch.
 */

const REPLAY_TABS = ["/macro/fed", "/macro/rates"] as const;

/** Console-error collector, matching `macro-desk.spec.ts:36-42`. */
function collectConsoleErrors(page: Page): string[] {
  const errors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  return errors;
}

function realErrors(errors: string[]): string[] {
  return errors.filter((message) => !/favicon/i.test(message));
}

test.describe("macro desk — replay chrome", () => {
  test("a live tab carries the control but no replay banner", async ({
    page,
  }) => {
    const consoleErrors = collectConsoleErrors(page);

    for (const href of REPLAY_TABS) {
      await page.goto(href);
      await page.waitForLoadState("networkidle");

      // The question is always on screen; the claim to be replaying is not.
      const control = page.getByTestId("macro-replay-control");
      await expect(control).toBeVisible();
      await expect(control).toHaveAttribute("data-replay-clock", "instant");
      await expect(page.getByTestId("macro-replay-is-live")).toBeVisible();

      // The whole point of driving the banner off the response: a live page must not be
      // able to display one, whatever the API returned.
      await expect(page.getByTestId("macro-replay-status")).toHaveCount(0);
      await expect(page.getByTestId("macro-replay-rejected")).toHaveCount(0);
    }

    expect(realErrors(consoleErrors)).toEqual([]);
  });

  test("a tab with no data path shows no picker at all", async ({ page }) => {
    // Tab 08 registers `replayClock: "none"`. An inert control over static prose would
    // advertise a capability the tab does not have — and, once tab 05 arrives, a picker
    // rendered by default is exactly how the obs-date tab would inherit the wrong
    // question (plan §3.1, settled §10-H).
    await page.goto("/macro/notes");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("macro-design-notes")).toBeVisible();
    await expect(page.getByTestId("macro-replay-control")).toHaveCount(0);
  });

  test("a replayed render differs from a live one, and says which instant it is", async ({
    page,
  }) => {
    for (const href of REPLAY_TABS) {
      await page.goto(href);
      await page.waitForLoadState("networkidle");
      const liveHasStatus = await page
        .getByTestId("macro-replay-status")
        .count();

      await page.goto(`${href}?as_of=2000-01-01`);
      await page.waitForLoadState("networkidle");

      const status = page.getByTestId("macro-replay-status");
      await expect(status).toBeVisible();

      // Not merely "different chrome": no rates snapshot can have been computed before
      // 2000-01-01, so the desk must WITHHOLD rather than draw the live curve under a
      // replay heading. `answered_after` here would mean the API ignored `as_of` — an
      // `argon-app` image without P1 answers a replay with the live snapshot and a 200
      // (§8, measured on the mini), and this is the assertion that catches it.
      await expect(status).toHaveAttribute("data-replay-state", "unanswered");
      await expect(page.getByTestId("macro-replay-live")).toBeVisible();

      // The desk's own header must be gone. `DeskHeader` renders these two titles, so
      // their absence is the proof that content was withheld and not just annotated.
      await expect(
        page.getByRole("heading", {
          name: /US Rates Factor Desk|Fed Policy Desk/,
          level: 1,
        }),
      ).toHaveCount(0);

      expect(liveHasStatus).toBe(0);
    }
  });

  test("the replay date survives a tab switch", async ({ page }) => {
    // Dropping it here would put a replayed tab beside a live one with nothing on screen
    // saying so — the exact failure §3.1 names as the worst a point-in-time desk has.
    await page.goto("/macro/fed?as_of=2000-01-01");
    await page.waitForLoadState("networkidle");

    await expect(page.getByTestId("macro-tab-rates")).toHaveAttribute(
      "href",
      "/macro/rates?as_of=2000-01-01",
    );
    await page.getByTestId("macro-tab-rates").click();
    await page.waitForLoadState("networkidle");

    expect(new URL(page.url()).searchParams.get("as_of")).toBe("2000-01-01");
    await expect(page.getByTestId("macro-replay-status")).toBeVisible();
  });

  test("a date that is not a date is named, not silently ignored", async ({
    page,
  }) => {
    const consoleErrors = collectConsoleErrors(page);

    await page.goto("/macro/rates?as_of=yesterday");
    await page.waitForLoadState("networkidle");

    // Rejected loudly...
    const rejected = page.getByTestId("macro-replay-rejected");
    await expect(rejected).toBeVisible();
    await expect(rejected).toContainText("as_of=yesterday");

    // ...and NOT dressed as a replay. Garbage that quietly resolves to live data under a
    // replay banner is the same lie as live data under a replay banner.
    await expect(page.getByTestId("macro-replay-status")).toHaveCount(0);
    await expect(page.getByTestId("macro-replay-is-live")).toBeVisible();

    // A rejected parameter must not take the tab down either.
    await expect(page.getByTestId("macro-tab-bar")).toBeVisible();
    expect(realErrors(consoleErrors)).toEqual([]);
  });

  test("the picker cannot ask what the desk will know tomorrow", async ({
    page,
  }) => {
    await page.goto("/macro/rates");
    await page.waitForLoadState("networkidle");

    const today = new Date().toISOString().slice(0, 10);
    await expect(page.getByTestId("macro-replay-date")).toHaveAttribute(
      "max",
      today,
    );
    // Stepping forward from today is capped rather than offered.
    await expect(page.getByTestId("macro-replay-next")).toHaveCount(0);
    await expect(page.getByTestId("macro-replay-next-capped")).toBeVisible();
  });
});
