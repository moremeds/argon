// Volatility Tab v2 — end-to-end smoke. Requires the dev DB to have at
// least one ticker with >=90 days of realized_volatility_history and SPY
// rows in index_ohlc_daily (see scripts/seed_spy_ohlc.py).
import { expect, test } from "@playwright/test";

const TICKER = "TSLA";

test("volatility tab renders all panels with no NaN / no console errors", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));

  await page.goto(`/stock/${TICKER}/volatility`);

  // VolMetricsCard header — DOM text is "Volatility"; CSS uppercases it.
  await expect(page.getByRole("heading", { name: "Volatility" })).toBeVisible({
    timeout: 30_000,
  });
  // At least one of the IV/RV metric labels.
  await expect(page.getByText("IV (ATM)")).toBeVisible();
  await expect(page.getByText("IV Rank").first()).toBeVisible();

  // Primary 2x2 chart grid.
  await expect(page.getByText("Term Structure")).toBeVisible();
  await expect(page.getByText("Smile")).toBeVisible();
  await expect(page.getByText("HV / IV")).toBeVisible();
  await expect(page.getByText("IV %ile Distribution")).toBeVisible();

  // Analytical row 2x2.
  await expect(page.getByText("IV / IV-of-IV")).toBeVisible();
  await expect(page.getByText("RV / SPY-corr-1m")).toBeVisible();
  await expect(page.getByText("Regime Quadrant")).toBeVisible();
  await expect(page.getByText("IV-z vs RV-z")).toBeVisible();

  // Bottom full-width VRP panel.
  await expect(page.getByText("VRP Spread")).toBeVisible();

  // No NaN text leaks anywhere on the page.
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/NaN/);

  // No console errors.
  expect(consoleErrors, consoleErrors.join("\n")).toHaveLength(0);
});

test("VRP tab route is removed", async ({ page }) => {
  const r = await page.goto(`/stock/${TICKER}/vrp`);
  // The [tab]/page.tsx calls notFound() for unknown slugs → 404.
  expect(r?.status()).toBe(404);
});

// Fresh-ticker backfill flow is covered by the backend integration test
// `test_volatility_series_endpoint_kicks_off_backfill_when_history_thin` —
// not duplicated here because /stock/<ticker> wrapper 500s for tickers
// missing the upstream SingleStockReport, which is unrelated to volatility.
