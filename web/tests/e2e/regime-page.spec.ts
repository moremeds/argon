import { expect, test } from "@playwright/test";

test("/regime renders with three tabs and GEX default", async ({ page }) => {
  await page.goto("/regime");
  await expect(page.getByRole("heading", { name: "Regime" })).toBeVisible();
  await expect(page.getByTestId("regime-tab-cri")).toBeVisible();
  await expect(page.getByTestId("regime-tab-vcg")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toBeVisible();
  await expect(page.getByTestId("regime-tab-gex")).toHaveClass(/active/);
});

test("CRI tab renders subtab — either empty state or populated cards", async ({
  page,
}) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-cri").click();
  // After click, either CriSubTab loads (data path) or the empty placeholder appears.
  await expect(
    page.getByTestId("cri-subtab").or(page.getByTestId("cri-empty-state")),
  ).toBeVisible({ timeout: 15_000 });
});

test("VCG tab renders subtab — either empty state or populated cards", async ({
  page,
}) => {
  await page.goto("/regime");
  await page.getByTestId("regime-tab-vcg").click();
  await expect(
    page.getByTestId("vcg-subtab").or(page.getByTestId("vcg-empty-state")),
  ).toBeVisible({ timeout: 15_000 });
});

test("vol backdrop strip renders with four vol tiles + term structure", async ({
  page,
}) => {
  await page.goto("/regime");
  // Strip is a client component that polls; wait for it to hydrate.
  await expect(page.getByText("VIX", { exact: true })).toBeVisible({
    timeout: 15_000,
  });
  await expect(page.getByText("VIX3M")).toBeVisible();
  await expect(page.getByText("VVIX")).toBeVisible();
  await expect(page.getByText("COR1M")).toBeVisible();
  await expect(page.getByText(/term structure/i)).toBeVisible();
  // Either contango or backwardation should appear once data loads.
  await expect(page.getByText(/contango|backwardation/i)).toBeVisible({
    timeout: 15_000,
  });
});

test("history chart renders inside GEX tab for SPX", async ({ page }) => {
  await page.goto("/regime");
  await expect(page.getByTestId("regime-tab-gex")).toHaveClass(/active/);
  // The HistoryChart renders an SVG with aria-label "<ticker> 90-day GEX history".
  // SPX is the default ticker; without history the empty-state copy appears instead.
  await expect(
    page
      .getByRole("img", { name: /90-day gex history/i })
      .or(page.getByText(/no history available/i)),
  ).toBeVisible({ timeout: 15_000 });
});
