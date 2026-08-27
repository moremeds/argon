// Prereq: `uv run python -m uw_scan.worker.gold_warmup` must have written at
// least one gold_posture_daily row before this runs — otherwise the page
// renders the "not yet computed" placeholder instead of the cockpit.
import { expect, test } from "@playwright/test";

test.describe("GOLD COMPASS /gold", () => {
  test("renders the five-tier cockpit when posture has been computed", async ({
    page,
  }) => {
    const consoleErrors: string[] = [];
    page.on("console", (msg) => {
      if (msg.type() === "error") consoleErrors.push(msg.text());
    });

    await page.goto("/gold");

    // Wordmark + sub-mark. The h1 is the final-render anchor (dev mode also
    // briefly shows "Loading GOLD COMPASS…" so we have to target the heading).
    await expect(
      page.getByRole("heading", { name: /GOLD COMPASS/i }),
    ).toBeVisible();

    // The five regions are aria-labelled by GoldCompassLayout. KPI strip is
    // tier 1; lens 1/2/3 follow; correlation history is the last region (it
    // also held a lens-decomposition panel until that panel's data source was
    // found to be empty by construction).
    await expect(page.getByRole("region", { name: /kpi/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /lens 1/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /lens 2/i })).toBeVisible();
    await expect(page.getByRole("region", { name: /lens 3/i })).toBeVisible();
    await expect(
      page.getByRole("region", { name: /correlation history/i }),
    ).toBeVisible();

    // Posture language: page must NOT contain sizing imperatives. Re-asserts
    // the runtime invariant that posture-lint enforces at build time.
    const body = (await page.textContent("body")) ?? "";
    expect(body.toLowerCase()).not.toMatch(/\bbuy\b/);
    expect(body.toLowerCase()).not.toMatch(/\bsell\b/);
    expect(body.toLowerCase()).not.toMatch(/\bposition size\b/);
    expect(body.toLowerCase()).not.toMatch(/\bpredicted return\b/);

    // No client-side React errors during render.
    expect(consoleErrors.filter((m) => !/favicon/i.test(m))).toEqual([]);
  });
});
