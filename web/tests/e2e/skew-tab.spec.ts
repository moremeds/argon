// Skew tab — end-to-end smoke. Requires the local dev DB (option_wizard_local)
// backfilled via the real worker path (worker/jobs/skew_analytics.skew_analytics_backfill
// + reports/skew_markout.run_skew_markout). AAPL has skew history locally.
// The panel is a positioning descriptor (no directional forecast) — see
// docs/research/skew-directional/README.md.
import { expect, test } from "@playwright/test";

// Ticker known to have skew history locally (verify with the G1/Step-3 query).
const TICKER = "AAPL";

test("Skew tab renders the descriptor read card and the spectrum", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() !== "error") return;
    const text = msg.text();
    if (text.includes("favicon.ico")) return;
    consoleErrors.push(text);
  });
  page.on("pageerror", (err) => consoleErrors.push(err.message));

  await page.goto(`/stock/${TICKER}/skew`);

  // Tab strip rendered; Skew tab present.
  await expect(page.getByRole("link", { name: "Skew" })).toBeVisible({
    timeout: 30_000,
  });

  // Skew Read card: deviation/drive/relative-value rows + factual context.
  await expect(page.getByText("Skew Read")).toBeVisible();
  await expect(page.getByText("Deviation")).toBeVisible();
  await expect(page.getByText("Relative value")).toBeVisible();
  await expect(page.getByText("Context")).toBeVisible();

  // No directional forecast: no BULLISH/BEARISH/NEUTRAL verdict word, no
  // "validated" stamp, no forward-return %, no suggested structure block.
  await expect(page.locator("text=/^(BULLISH|BEARISH|NEUTRAL)$/")).toHaveCount(
    0,
  );
  await expect(page.getByTestId("skew-structure-detail")).toHaveCount(0);
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/validated/i);
  expect(body).not.toMatch(/\/20d/);

  // Secondary panels render.
  await expect(page.getByText("FRONT vs BACK")).toBeVisible(); // skew-term panel
  await expect(page.getByText("WHERE IT SITS")).toBeVisible(); // asset-class spectrum

  // No NaN leaks anywhere on the page.
  expect(body).not.toMatch(/NaN/);

  // Evidence artifact for the PR (playwright runs from web/, so escape to root).
  await page.screenshot({
    path: `../output/playwright/skew-tab-${TICKER}.png`,
    fullPage: true,
  });

  // No console errors.
  expect(consoleErrors, consoleErrors.join("\n")).toHaveLength(0);
});
