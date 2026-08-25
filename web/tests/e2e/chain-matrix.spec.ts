import { expect, test } from "@playwright/test";

const ENGINE = "fundamentals-v2:77aea364";
const URL = `/chains?engine=${encodeURIComponent(ENGINE)}`;

/** The matrix's gate is that it DESCRIBES and does not CONDUCT. Argon measured
 *  the alternative: the capex-demand ledger's cross-name relationship collapsed
 *  from +0.247 to +0.015 (p=0.44) among same-sector pairs. */

test("the matrix states how little exposure is actually disclosed", async ({
  page,
}) => {
  await page.goto(URL);
  await expect(
    page.getByRole("heading", { name: "Industry chain matrix" }),
  ).toBeVisible();
  await expect(
    page.getByText(/memberships carry a\s+disclosed\s+economic magnitude/),
  ).toBeVisible();
});

test("it refuses a causal reading in writing", async ({ page }) => {
  await page.goto(URL);
  await page.getByText("What this matrix may not be read as").click();
  await expect(page.getByText(/no edge in this taxonomy has demonstrated/)).toBeVisible();
  await expect(page.getByText(/supplier\/customer relationship/)).toBeVisible();
});

test("an abstaining cell says so instead of rendering blank", async ({ page }) => {
  await page.goto(`/chains?engine=${encodeURIComponent("fundamentals-v1:77aea364")}`);
  // v1 writes no dimensions, so every cell must abstain — and must SAY it.
  await expect(page.getByText("abstains").first()).toBeVisible();
});

test("a cell opens its member list with each placement's evidence", async ({
  page,
}) => {
  await page.goto(`${URL}&domain=optical_communication`);
  await page.locator("button", { hasText: "Module-Transceiver" }).first().click();
  await page.getByText("Open the member list").click();
  await expect(page.getByRole("columnheader", { name: "Placed by" })).toBeVisible();
  // The normal state is an undisclosed magnitude, and it must read as a state
  // rather than as a data gap.
  await expect(page.getByText("not disclosed").first()).toBeVisible();
});

test("screenshot artifact", async ({ page }) => {
  await page.goto(`${URL}&domain=optical_communication`);
  // Wait for CONTENT, not for any button — the sidebar's buttons exist while the
  // page still says "Loading dashboard…", which is what the first capture got.
  await page.getByRole("heading", { name: "Industry chain matrix" }).waitFor();
  await page.getByText("Module-Transceiver").first().waitFor();
  await page.screenshot({ path: "../output/playwright/chain-matrix.png" });
});
