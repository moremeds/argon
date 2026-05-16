import { expect, test } from "@playwright/test";

test("/regime renders with three tabs and GEX default", async ({ page }) => {
  await page.goto("/regime");
  await expect(page.getByRole("heading", { name: "Regime" })).toBeVisible();
  await expect(page.getByTestId("regime-tab-cri")).toBeVisible();
  await expect(page.getByTestId("regime-tab-vcg")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toHaveClass(/active/);
});

test("CRI tab shows pending placeholder", async ({ page }) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-cri").click();
  await expect(page.getByText(/coming soon/i)).toBeVisible();
});
