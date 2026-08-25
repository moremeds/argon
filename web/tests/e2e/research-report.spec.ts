import { expect, test } from "@playwright/test";

/** A versioned report's product is the DELTA. These check that the surface
 *  cannot render a report without what changed, that a method change is stated
 *  apart from value moves, and that an old version serves its frozen content
 *  rather than today's data wearing an old version number. */

const CHAIN = "/reports/chain/Optical-Communication";

test("the listing links each report at its newest version", async ({ page }) => {
  await page.goto("/reports");
  await expect(page.getByRole("heading", { name: "Research reports" })).toBeVisible();
  await expect(
    page.getByRole("link", { name: "Optical-Communication chain report" }),
  ).toBeVisible();
});

test("a report states its frozen manifest and its content hash", async ({ page }) => {
  await page.goto(CHAIN);
  await expect(
    page.getByRole("heading", { name: "Optical-Communication chain report" }),
  ).toBeVisible();
  await expect(page.getByText("Evidence policy")).toBeVisible();
  await expect(page.getByText(/content hash/)).toBeVisible();
  await expect(page.getByText(/never from today's data/)).toBeVisible();
});

test("what the report cannot answer is a section, not a footnote", async ({
  page,
}) => {
  await page.goto(CHAIN);
  await expect(
    page.getByRole("heading", { name: "What this report cannot answer" }),
  ).toBeVisible();
  // A killed class must be named, not silently omitted.
  await expect(page.getByText("customer_concentration").first()).toBeVisible();
});

test("the delta sits above the content", async ({ page }) => {
  await page.goto(CHAIN);
  await expect(
    page.getByRole("heading", { name: "Since the previous version" }),
  ).toBeVisible();
  const delta = await page
    .getByRole("heading", { name: "Since the previous version" })
    .boundingBox();
  const firstBlock = await page
    .getByRole("heading", { name: "Coverage and denominators" })
    .boundingBox();
  expect(delta!.y).toBeLessThan(firstBlock!.y);
});

test("an old version serves its frozen numbers", async ({ page }) => {
  await page.goto(`${CHAIN}?version=1`);
  await expect(page.getByText("v1 · superseded")).toBeVisible();
  await expect(page.getByText("First version")).toBeVisible();
});

test("screenshot artifact", async ({ page }) => {
  await page.goto(CHAIN);
  await page
    .getByRole("heading", { name: "Optical-Communication chain report" })
    .waitFor();
  await page.getByRole("heading", { name: "Aggregate priority" }).waitFor();
  await page.screenshot({
    path: "../output/playwright/research-report.png",
    fullPage: true,
  });
});
