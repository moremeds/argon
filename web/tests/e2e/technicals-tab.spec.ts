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
  // Either real panels or the honest empty state — both are valid renders.
  await expect(
    page.getByText(/Z-SCORE|No technicals history/i).first(),
  ).toBeVisible();
  const body = (await page.textContent("body")) ?? "";
  expect(body).not.toMatch(/NaN/);
  expect(consoleErrors).toHaveLength(0);
});
