import { expect, test, type Page } from "@playwright/test";

const consoleErrors = new WeakMap<Page, string[]>();

test.beforeEach(async ({ page }) => {
  const errors: string[] = [];
  consoleErrors.set(page, errors);
  page.on("console", (msg) => {
    if (msg.type() === "error") errors.push(msg.text());
  });
  await page.route(
    /\/stock\/DRYRUN\/(?!technicals|magnets)(?:[^?]*)/,
    (route) =>
      route.fulfill({ status: 200, contentType: "text/x-component", body: "" }),
  );
  await page.goto("/stock/DRYRUN/technicals");
  await page.getByTestId("magnet-view-toggle").getByText("MAGNET VIEW").click();
});

test("magnet chart renders without console errors or NaN", async ({ page }) => {
  await expect(page.getByTestId("magnet-chart")).toBeVisible();
  // Scoped to the sub-tab, NOT document.body: body textContent includes Next's
  // RSC flight payload, whose <script> blocks are full of literal "$undefined"
  // markers. Asserting over the whole body fails on the framework's own
  // serialisation and says nothing about what the user sees.
  const view = (await page.getByTestId("magnet-subtab").innerText()) ?? "";
  expect(view).not.toMatch(/NaN/);
  expect(view).not.toMatch(/undefined/);
  expect(consoleErrors.get(page)).toHaveLength(0);
});

test("the 0.618 rows are labelled as having no measured edge", async ({
  page,
}) => {
  await expect(page.getByText(/no measured edge/i).first()).toBeVisible();
  // The failed geometry must never carry a percentage.
  const view = (await page.getByTestId("magnet-subtab").innerText()) ?? "";
  expect(view).not.toMatch(/0\.618[^.]{0,40}%/);
});

test("band legend shows the interval, not a bare point estimate", async ({
  page,
}) => {
  await expect(page.getByText(/held \d+% of moves \(\d/)).toBeVisible();
});

test("the sub-view choice survives a reload", async ({ page }) => {
  await page.reload();
  await expect(page.getByTestId("magnet-chart")).toBeVisible();
});
