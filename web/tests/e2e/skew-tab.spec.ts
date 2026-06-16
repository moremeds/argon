// Skew tab — end-to-end smoke. Requires the local dev DB (option_wizard_local)
// backfilled via the real worker path (worker/jobs/skew_analytics.skew_analytics_backfill
// + reports/skew_markout.run_skew_markout). AAPL has skew history locally and a
// non-NEUTRAL lean, so this also exercises the colored lean badge.
import { expect, test } from "@playwright/test";

// Ticker known to have skew history locally (verify with the G1/Step-3 query).
const TICKER = "AAPL";

test("Skew tab renders the signal-detail card, lean, and the spectrum", async ({
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

  // Merged Signal Detail card: deviation/drive/relative-value rows + evidence.
  await expect(page.getByText("Signal Detail")).toBeVisible();
  await expect(page.getByText("Deviation")).toBeVisible();
  await expect(page.getByText("Relative value")).toBeVisible();
  await expect(page.getByText("Evidence")).toBeVisible();

  // Lean surfaces as one of the three states (header pill + evidence column).
  const lean = page.locator("text=/^(BULLISH|BEARISH|NEUTRAL)$/").first();
  await expect(lean).toBeVisible();

  // Secondary panels render.
  await expect(page.getByText("FRONT vs BACK")).toBeVisible(); // skew-term panel
  await expect(page.getByText("WHERE IT SITS")).toBeVisible(); // asset-class spectrum

  // Structure detail (Phase-2): present iff the lean is non-neutral. A NEUTRAL name
  // (the ~72% default) shows no structure block; a gated name shows >=2 defined-risk legs.
  const leanText = ((await lean.textContent()) ?? "").trim();
  const structure = page.getByTestId("skew-structure-detail");
  if (leanText === "NEUTRAL") {
    await expect(structure).toHaveCount(0);
  } else {
    await expect(structure).toBeVisible();
    await expect(structure).toContainText(/-spread/);
    await expect(structure.getByText(/^(BUY|SELL) (PUT|CALL)$/)).toHaveCount(2);
  }

  // No NaN leaks anywhere on the page.
  const body = await page.locator("body").innerText();
  expect(body).not.toMatch(/NaN/);

  // Evidence artifact for the PR (playwright runs from web/, so escape to root).
  await page.screenshot({
    path: `../output/playwright/skew-tab-${TICKER}.png`,
    fullPage: true,
  });

  // No console errors.
  expect(consoleErrors, consoleErrors.join("\n")).toHaveLength(0);
});
