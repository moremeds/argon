import { expect, test } from "@playwright/test";

test.describe("/scanner page", () => {
  test("loads and renders the header", async ({ page }) => {
    await page.goto("/scanner");

    await expect(page.getByRole("heading", { name: "SCANNER" })).toBeVisible();
  });

  test("filter chip toggles URL search param", async ({ page }) => {
    await page.goto("/scanner");

    const typeFCheckbox = page.getByLabel("Type F only");
    await typeFCheckbox.check();

    await expect(page).toHaveURL(/type_f_only=true/);
  });
});
