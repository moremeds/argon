// Prereq: `bash scripts/migrate.sh` + at least one scan_runs row + watchlist_card
// row. Run `uv run python -m uw_scan.worker.jobs.full_scan` once before E2E if
// cards are missing — an empty grid will fail the locator on the first card.
import { test, expect } from "@playwright/test";

test("dashboard → detail → tab → rescan", async ({ page }) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "DASHBOARD" })).toBeVisible();

  const firstCard = page.locator("a[href^='/stock/']").first();
  const href = await firstCard.getAttribute("href");
  const ticker = href?.split("/").pop();
  if (!ticker) throw new Error("no ticker card visible — seed the DB first");
  await firstCard.click();

  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/market-structure`));
  await page.getByRole("link", { name: /flow/i }).click();
  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/flow`));

  await page.goto("/");
  // The button's text changes after click (rescan → queued… → running… →
  // done), so locating by initial text won't survive the click. The card
  // exposes its link via aria-label="<TICKER> detail"; the RescanButton is
  // a sibling of the link inside the same card wrapper.
  const card = page
    .locator("a[aria-label$='detail']")
    .first()
    .locator("xpath=..");
  const rescan = card.locator("button").first();
  await expect(rescan).toHaveText("rescan");
  await rescan.click();
  await expect(rescan).toHaveText(/queued|running|done/, { timeout: 5000 });
});
