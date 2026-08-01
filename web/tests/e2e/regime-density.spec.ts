import { expect, test } from "@playwright/test";

test.describe("Regime Market Compass — SPX density cone", () => {
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

  test("tab is labelled Market Compass and the cone leads the tab", async ({
    page,
  }) => {
    await page.goto("/regime/tide");
    await expect(page.getByTestId("regime-tab-tide")).toHaveText(
      "Market Compass",
    );
    // Ordering is the point of the move: the cone must precede the tide charts.
    const panel = page.getByTestId("spx-density-panel");
    const tide = page.getByTestId("market-tide-subtab");
    await expect(panel).toBeVisible();
    const order = await tide.evaluate((root) => {
      const kids = Array.from(root.children);
      return kids.findIndex((k) =>
        k.querySelector('[data-testid="spx-density-panel"]'),
      );
    });
    expect(order).toBe(0);
  });

  test("the chart canvas mounts and survives a view switch", async ({
    page,
  }) => {
    await page.goto("/regime/tide");
    await page.waitForLoadState("networkidle");
    const chart = page.getByTestId("spx-density-chart");
    // Skip when no cone has been issued in this environment — the panel then
    // renders its empty state instead, which the first test already covers.
    if ((await chart.count()) === 0) test.skip();

    // lightweight-charts mounts a real <canvas>; this is the check that jsdom
    // cannot do and the reason the unit test mocks this component out.
    await expect(chart.locator("canvas").first()).toBeVisible();
    await page.getByRole("button", { name: /1–5 day fan/i }).click();
    await expect(chart.locator("canvas").first()).toBeVisible();
    await page.getByRole("button", { name: /next session/i }).click();
    await expect(chart.locator("canvas").first()).toBeVisible();
  });
});
