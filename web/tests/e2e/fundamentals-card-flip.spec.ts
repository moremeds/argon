import { expect, test } from "@playwright/test";

// The tab is a path segment, not a query param.
const URL = "/stock/NVDA/fundamentals";

test("a fundamental card flips to its own components", async ({ page }) => {
  await page.goto(URL);
  const tile = page.getByTestId("subscore-gross_margin");
  await expect(tile).toBeVisible();

  await tile.click();

  const back = page.getByTestId("subscore-back-gross_margin");
  await expect(back).toBeVisible();
  // The bars are the point: assert the chart drew, not merely that text changed.
  await expect(back.locator("rect[data-series]").first()).toBeVisible();
  await expect(back.getByText(/quarterly/)).toBeVisible();
  await expect(back.getByText(/USD/)).toBeVisible();
  await expect(tile).toBeHidden();

  // Clicking the card again is the way back — the same gesture that opened it.
  await back.click();
  await expect(page.getByTestId("subscore-gross_margin")).toBeVisible();
  await expect(back).toBeHidden();
});

test("the tile opens on Enter and closes on Escape", async ({ page }) => {
  // This is the coverage the vitest suite deliberately does NOT claim: jsdom
  // does not synthesise a click from a keydown, so native button activation can
  // only be proven in a real browser. Asserted here rather than faked there.
  await page.goto(URL);
  const tile = page.getByTestId("subscore-gross_margin");
  await expect(tile).toBeVisible();

  await tile.focus();
  await page.keyboard.press("Enter");
  await expect(page.getByTestId("subscore-back-gross_margin")).toBeVisible();

  await page.keyboard.press("Escape");
  await expect(page.getByTestId("subscore-gross_margin")).toBeVisible();
});

test("the eighth card renders and is marked not scored", async ({ page }) => {
  await page.goto(URL);
  const eighth = page.getByTestId("subscore-revenue_earnings");
  await expect(eighth).toBeVisible();
  await expect(eighth).toContainText(/not scored/i);
});
