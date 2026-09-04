import { readFileSync } from "node:fs";
import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

import { expect, test } from "@playwright/test";

/**
 * Flash, end to end, against a row seeded through the real ingest endpoint.
 *
 * The seed is the recorded option-wizard premarket run of 2026-09-03, posted
 * the way helium posts it — never a direct INSERT. A fixture that reaches the
 * page by a private door proves the page, not the path.
 */
const API = "http://127.0.0.1:8400";
const TOKEN = process.env.UW_SCAN_AGENT_INGEST_TOKEN ?? "flash-e2e-local-token";
const HERE = dirname(fileURLToPath(import.meta.url));
const RUN = JSON.parse(
  readFileSync(
    resolve(HERE, "../../../tests/fixtures/flash/2026-09-03-premarket.json"),
    "utf8",
  ),
) as Record<string, unknown>;

const WEEK = "2026-W36";
const DAY = "2026-09-03";
const EMPTY_DAY = "2026-08-31";

test.beforeAll(async ({ request }) => {
  const res = await request.post(`${API}/api/agent-runs`, {
    headers: { Authorization: `Bearer ${TOKEN}` },
    data: RUN,
  });
  // 201 on the first post of a session, 200 on every re-run: the ingest is
  // idempotent on (tenant, run_id) and a re-run must not be a failure.
  expect([200, 201]).toContain(res.status());
});

test("the sidebar carries Flash and it lands on a recorded week", async ({
  page,
}) => {
  await page.goto("/");
  const link = page.locator('nav a[href="/flash"]');
  await expect(link).toContainText("Flash");
  await expect(link).toContainText("agent news flash");
  await link.click();
  await expect(page).toHaveURL(/\/flash\/\d{4}-W\d{2}$/);
});

test("the week strip lights only the phases that were recorded", async ({
  page,
}) => {
  await page.goto(`/flash/${WEEK}`);
  const card = page.getByTestId(`flash-day-${DAY}`);
  await expect(card.getByTestId("pip-premarket")).toHaveAttribute(
    "data-on",
    "true",
  );
  await expect(card.getByTestId("pip-intraday")).toHaveAttribute(
    "data-on",
    "false",
  );
  await expect(card.getByTestId("pip-close")).toHaveAttribute(
    "data-on",
    "false",
  );
  await card.click();
  await expect(page).toHaveURL(new RegExp(`/flash/${WEEK}/${DAY}`));
});

test("the premarket page renders the report and never a position size", async ({
  page,
}) => {
  await page.goto(`/flash/${WEEK}/${DAY}?phase=premarket`);
  await expect(page.getByText(/Real yields did the work/).first()).toBeVisible();
  await expect(page.getByTestId("decision-key").first()).toBeVisible();
  await expect(
    page.getByRole("img", { name: /Profit and loss at expiry/ }).first(),
  ).toBeVisible();
  // Scoped to the candidate cards, not the page: the defined-risk footer
  // legitimately contains the words "position sizes" — it is the sentence that
  // PROMISES there are none. Asserting over the whole page would fail on the
  // very line that states the rule.
  const cards = page.getByTestId(/^flash-candidate-/);
  await expect(cards.first()).toBeVisible();
  for (const text of await cards.allInnerTexts()) {
    expect(text).not.toMatch(/net liq|position size|contracts to buy|\bqty\b/i);
  }
  await expect(
    page.getByText(
      /All structures are defined-risk\. No quantities, position sizes/,
    ),
  ).toBeVisible();
});

test("a day with no run says so, and says what it queried", async ({ page }) => {
  await page.goto(`/flash/${WEEK}/${EMPTY_DAY}?phase=premarket`);
  await expect(page.getByText("No run recorded", { exact: true })).toBeVisible();
  await expect(page.getByText(/helium audit — 0 runs/)).toBeVisible();
});

test("the desktop layout does not scroll sideways at 1440", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 900 });
  await page.goto(`/flash/${WEEK}/${DAY}?phase=premarket`);
  const overflow = await page.evaluate(
    () =>
      document.documentElement.scrollWidth -
      document.documentElement.clientWidth,
  );
  expect(overflow).toBeLessThanOrEqual(0);
});
