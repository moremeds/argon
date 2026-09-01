import { expect, test } from "@playwright/test";

test("Canary history layout — full screenshot for visual verification", async ({
  page,
}) => {
  // Full-page screenshot of a chart-heavy tab; needs more than the 30s default.
  test.setTimeout(60_000);
  await page.setViewportSize({ width: 1440, height: 2000 });
  await page.goto("/regime");
  await page.getByTestId("regime-tab-canary").click();
  await expect(page.getByTestId("canary-score-chart")).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByTestId("canary-history-table")).toBeVisible();
  // Pause briefly to let SVG measurement (ResizeObserver) settle.
  await page.waitForTimeout(500);
  await page.screenshot({
    path: "output/playwright/canary-history-layout.png",
    fullPage: true,
  });
});
