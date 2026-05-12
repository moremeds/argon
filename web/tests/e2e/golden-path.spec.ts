// Prereq: `bash scripts/migrate.sh` + at least one scan_runs row + watchlist_card
// row. Run `uv run python -m uw_scan.worker.jobs.full_scan` once before E2E if
// cards are missing — an empty grid will fail the locator on the first card.
import { test, expect } from "@playwright/test";

test("watchlist → detail → tab → rescan", async ({ page }) => {
  await page.goto("/watchlist");
  await expect(page.getByText("WATCHLIST")).toBeVisible();

  const firstCard = page.locator("a[href^='/stock/']").first();
  const href = await firstCard.getAttribute("href");
  const ticker = href?.split("/").pop();
  if (!ticker) throw new Error("no ticker card visible — seed the DB first");
  await firstCard.click();

  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/market-structure`));
  await page.getByRole("link", { name: /flow/i }).click();
  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/flow`));

  await page.goto("/watchlist");
  await page.locator("button:has-text('rescan')").first().click();
  await expect(page.locator("button:has-text('queued')").first()).toBeVisible({
    timeout: 3000,
  });
});
