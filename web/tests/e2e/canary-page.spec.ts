import { expect, test } from "@playwright/test";

test("/regime exposes the 5% Canary tab", async ({ page }) => {
  await page.goto("/regime");
  await expect(page.getByTestId("regime-tab-canary")).toBeVisible();
  await expect(page.getByTestId("regime-tab-canary")).toContainText(
    /5% CANARY/,
  );
});

test("5% Canary tab renders empty-state or populated subtab", async ({
  page,
}) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-canary").click();
  // Either the populated CanarySubTab loads or the empty placeholder appears.
  // The empty path fires when no snapshot exists at the current
  // composite_version (the API returns 503; useSyncHook surfaces it as error).
  await expect(
    page
      .getByTestId("canary-subtab")
      .or(page.getByTestId("canary-empty-state"))
      .or(page.getByTestId("canary-loading")),
  ).toBeVisible({ timeout: 15_000 });
});

test("Validation sub-tab exposes 5% Canary entry", async ({ page }) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-validation").click();
  await expect(page.getByTestId("validation-sub-canary")).toBeVisible();
  await expect(page.getByTestId("validation-sub-canary")).toContainText(
    /5% CANARY/,
  );
  await page.getByTestId("validation-sub-canary").click();
  await expect(
    page
      .getByTestId("canary-validation-panel")
      .or(page.getByTestId("canary-validation-empty")),
  ).toBeVisible({ timeout: 15_000 });
});
