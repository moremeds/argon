import { expect, test } from "@playwright/test";

test.describe("Regime GRG tab", () => {
  test("deep-links to /regime/grg with the GRG tab active", async ({
    page,
  }) => {
    await page.goto("/regime/grg");
    // Tab strip rendered and GRG is the active tab.
    await expect(page.getByTestId("regime-tabs")).toBeVisible();
    await expect(page.getByTestId("regime-tab-grg")).toHaveClass(/active/);
    // Either the populated panel or the empty-state renders (both are valid
    // depending on whether a snapshot exists locally).
    const panel = page.getByTestId("grg-panel");
    const empty = page.getByTestId("grg-empty");
    await expect(panel.or(empty)).toBeVisible();
    // Evidence artifact for the PR.
    await page.screenshot({
      path: "../output/playwright/regime-grg.png",
      fullPage: true,
    });
  });

  test("clicking the GRG tab updates the URL", async ({ page }) => {
    await page.goto("/regime/gex");
    await page.getByTestId("regime-tab-grg").click();
    await expect(page).toHaveURL(/\/regime\/grg$/);
    await expect(page.getByTestId("regime-tab-grg")).toHaveClass(/active/);
  });
});
