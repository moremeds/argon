import { expect, test } from "@playwright/test";

test.describe("Regime Market Tide — SPX density cone", () => {
  test("renders the density cone panel on the tide tab", async ({ page }) => {
    await page.goto("/regime/tide");
    // Let the first GET /api/regime/spx-density settle so we don't race the
    // null-initial render.
    await page.waitForLoadState("networkidle");
    await expect(page.getByTestId("market-tide-subtab")).toBeVisible();
    // The panel renders in every state (loading / empty / populated) — the
    // testid is the contract, so this holds with or without issued rows.
    await expect(page.getByTestId("spx-density-panel")).toBeVisible();
  });
});
