import { expect, test } from "@playwright/test";

const ENGINE = "fundamentals-v2:77aea364";
const URL = `/radar?engine=${encodeURIComponent(ENGINE)}`;

/** The Radar's gate is not "does it render" — it is "does it render what the
 *  evidence permits, and does it say what it does not know". Each test below is
 *  one clause of that. */

test("the radar renders its scope and its own denominator", async ({ page }) => {
  await page.goto(URL);
  await expect(
    page.getByRole("heading", { name: "Fundamental PM Research Radar" }),
  ).toBeVisible();

  // The denominator, stated. A table of 400 rows over a 449-name universe is a
  // different object from a complete one, and the difference is invisible
  // unless it is written down.
  await expect(
    page.getByText(/names have no\s+compatible result and are absent/),
  ).toBeVisible();
});

test("the ordering discloses the permission it exercises", async ({ page }) => {
  await page.goto(URL);
  await expect(page.getByText("research_priority").first()).toBeVisible();
  // And what it may NOT be read as — the registry's prohibitions, verbatim.
  await page
    .getByText("What this ordering may not be read as")
    .click();
  await expect(page.getByText(/expected return/)).toBeVisible();
  await expect(page.getByText(/risk score/)).toBeVisible();
});

test("a rank driven by an extreme dimension is marked, not hidden", async ({
  page,
}) => {
  await page.goto(URL);
  const toggle = page.getByLabel(/Show names whose rank is driven by an extreme/);
  await expect(toggle).toBeChecked();

  const before = await page.locator("tbody tr").count();
  await toggle.uncheck();
  const after = await page.locator("tbody tr").count();
  // Unchecking must REMOVE rows, which proves the flag is populated rather than
  // being a control over an empty set.
  expect(after).toBeLessThan(before);
});

test("screenshot artifact", async ({ page }) => {
  await page.goto(URL);
  await page.waitForSelector("tbody tr");
  await page.screenshot({
    path: "../output/playwright/radar-page.png",
    fullPage: false,
  });
});
