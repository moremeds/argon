// Prereq (same as golden-path.spec.ts): the watchlist must contain at least
// one card for TICKER, and ideally its sector has 2+ tickers so the reorder
// assertion below has something to prove.
import { expect, test } from "@playwright/test";

const TICKER = "TSLA";

test("pin toggle persists via API and reorders card within sector", async ({
  page,
}) => {
  await page.goto("/");
  await expect(page.getByRole("heading", { name: "DASHBOARD" })).toBeVisible();

  // PinButton renders aria-label="Pin <T>" when unpinned, "Unpin <T>" when pinned,
  // and aria-pressed reflects the pinned prop. Match either form.
  const pin = page.getByRole("button", {
    name: new RegExp(`^(Pin|Unpin) ${TICKER}$`),
  });
  await expect(pin).toBeVisible();
  const initiallyPinned = (await pin.getAttribute("aria-pressed")) === "true";

  // Toggle once: click → patchTicker → router.refresh → new aria-pressed.
  await pin.click();
  await expect(pin).toHaveAttribute("aria-pressed", String(!initiallyPinned), {
    timeout: 5000,
  });

  if (!initiallyPinned) {
    // Newly pinned: card must now be first in its sector grid.
    const sectorGrid = page
      .locator("section")
      .filter({ has: page.getByLabel(`${TICKER} detail`) })
      .locator("div")
      .first();
    const firstAriaLabel = await sectorGrid
      .locator("[aria-label$=' detail']")
      .first()
      .getAttribute("aria-label");
    expect(firstAriaLabel).toBe(`${TICKER} detail`);
  }

  // Restore original state to keep the suite idempotent.
  await pin.click();
  await expect(pin).toHaveAttribute("aria-pressed", String(initiallyPinned), {
    timeout: 5000,
  });
});
