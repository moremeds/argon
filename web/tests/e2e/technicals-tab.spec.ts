import { expect, test } from "@playwright/test";

const TICKER = "DRYRUN";

test("technicals tab renders with no NaN / no console errors", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  await page.goto(`/stock/${TICKER}/technicals`);
  // Real panels, the honest technicals empty state, or the page-level
  // "ticker not ready" guard (unscanned ticker) — all three are valid renders.
  await expect(
    page.getByText(/Z-SCORE|No technicals history|not ready/i).first(),
  ).toBeVisible();
  const body = (await page.textContent("body")) ?? "";
  expect(body).not.toMatch(/NaN/);
  expect(consoleErrors).toHaveLength(0);
});

test("overlay toggle flips SMA/EMA legend without console errors", async ({
  page,
}) => {
  const consoleErrors: string[] = [];
  page.on("console", (msg) => {
    if (msg.type() === "error") consoleErrors.push(msg.text());
  });
  await page.goto(`/stock/${TICKER}/technicals`);
  const toggle = page.getByRole("button", { name: "EMA·BB" });
  // Toggle only exists when the price pane rendered (i.e. history present);
  // on the empty state this test degrades to the render smoke.
  if (await toggle.isVisible().catch(() => false)) {
    // Assert on "EMA5" only — unique to the price-pane legend; "SMA20" also
    // appears in detail tiles and would trip Playwright strict mode.
    await toggle.click();
    await expect(page.getByText("EMA5", { exact: true })).toBeVisible();
    await page.getByRole("button", { name: "SMA·σ" }).click();
    await expect(page.getByText("EMA5", { exact: true })).not.toBeVisible();
  }
  expect(consoleErrors).toHaveLength(0);
});
