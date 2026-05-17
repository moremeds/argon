// Prereq: `bash scripts/migrate.sh` + at least one scan_runs row + watchlist_card
// row. Run `uv run python -m uw_scan.worker.jobs.full_scan` once before E2E if
// cards are missing — an empty grid will fail the locator on the first card.
import { test, expect } from "@playwright/test";

test("dashboard → detail → tab → rescan", async ({ page }) => {
  const ticker = "TSLA";

  await page.goto("/");
  await expect(page.getByRole("heading", { name: "DASHBOARD" })).toBeVisible();

  await page.getByLabel(`${ticker} detail`).click();

  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/market-structure`));
  await page.getByRole("link", { name: /flow/i }).click();
  await expect(page).toHaveURL(new RegExp(`/stock/${ticker}/flow`));

  await page.goto("/");
  // The button's visible text changes after click (rescan → queued… → running…
  // → done), so we locate by aria-label which is stable across status changes.
  const rescan = page.getByRole("button", { name: `rescan ${ticker}` });
  await expect(rescan).toHaveText("rescan");
  await rescan.click();
  await expect(rescan).toHaveText(/queued|running|done/, { timeout: 5000 });
});
