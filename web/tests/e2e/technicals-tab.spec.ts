import { expect, test, type Page } from "@playwright/test";

const TICKER = "DRYRUN";
const consoleErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  consoleErrors.set(page, errors);
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await page.route(/\/stock\/DRYRUN\/(?!technicals)(?:[^?]*)/, (route) =>
    route.fulfill({ status: 200, contentType: "text/x-component", body: "" }),
  );
  await page.goto(`/stock/${TICKER}/technicals`);
  await expect(page.getByTestId("technicals-price-chart")).toBeVisible();
});

test("technicals chart renders volume MA without console errors", async ({ page }) => {
  await expect(page.getByTestId("technicals-price-chart")).toHaveAttribute(
    "data-volume-ma",
    "50",
  );
  const body = (await page.textContent("body")) ?? "";
  expect(body).not.toMatch(/NaN/);
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("overlay toggle flips SMA/EMA legend without console errors", async ({
  page,
}) => {
  const toggle = page.getByRole("button", { name: "EMA·BB" });
  await expect(toggle).toBeVisible();
  await toggle.click();
  await expect(page.getByText("EMA5", { exact: true })).toBeVisible();
  await page.getByRole("button", { name: "SMA·σ" }).click();
  await expect(page.getByText("EMA5", { exact: true })).not.toBeVisible();
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("chart controls wrap inside the existing header on mobile", async ({ page }) => {
  await page.setViewportSize({ width: 390, height: 844 });
  await page.reload();
  const controls = page.getByTestId("technicals-chart-controls");
  await expect(controls).toBeVisible();
  await expect(page.getByRole("button", { name: "EMA·BB" })).toBeVisible();
  await expect(page.getByRole("button", { name: /Reset zoom/i })).toBeVisible();
  await expect(page.getByRole("button", { name: "Chart timeframe" })).toBeVisible();
  expect(
    await controls.evaluate((el) => el.scrollWidth <= el.clientWidth),
  ).toBe(true);
});
