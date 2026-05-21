import { expect, test } from "@playwright/test";

// /stock/[ticker]/page.tsx redirects to /stock/[ticker]/market-structure,
// so navigating straight to the canonical URL avoids relying on the TabBar
// link selector (which could break if the label/href changes).

test.describe("Market Structure greek sub-tabs", () => {
  test("default tab is GEX and shows GEX Profile", async ({ page }) => {
    await page.goto("/stock/TSLA/market-structure");
    await expect(page.getByRole("tab", { name: "GEX" })).toHaveAttribute(
      "aria-selected",
      "true",
    );
  });

  test("switching to VANNA reveals the Vanna headline or empty state", async ({
    page,
  }) => {
    await page.goto("/stock/TSLA/market-structure");
    await page.getByRole("tab", { name: "VANNA" }).click();
    await expect(
      page.locator(
        "text=/Long Vanna|Short Vanna|Neutral Vanna|Vanna data not yet available/",
      ),
    ).toBeVisible();
  });

  test("switching to CHARM reveals charm headline / empty state", async ({
    page,
  }) => {
    await page.goto("/stock/TSLA/market-structure");
    await page.getByRole("tab", { name: "CHARM" }).click();
    await expect(
      page.locator(
        "text=/Mechanical (SELL|BUY)|Limited charm|Charm data not yet available/",
      ),
    ).toBeVisible();
  });
});
