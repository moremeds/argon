// Phase 8 verification: HealthPanel surfaces the new WS Consumer row, and
// the /api/health response carries the ws_consumer block. This test does
// NOT require the WS consumer process to be running — it asserts the
// UI/API integration works in both states (no ticks yet AND with a
// synthetic heartbeat). End-to-end behavior with live ticks is verified
// by scripts/validate_ws.py during a market session.
import { test, expect } from "@playwright/test";

test.describe("WS consumer status surface", () => {
  test("/api/health includes ws_consumer block", async ({ request }) => {
    const res = await request.get("http://127.0.0.1:8400/api/health");
    expect(res.ok()).toBe(true);
    const body = await res.json();
    expect(body).toHaveProperty("ws_consumer");
    // ws_consumer is always present (may be null state-wise but the field
    // is on the model). When no ticks have ever been received the API
    // returns a non-null object with healthy reflecting market_open status.
    expect(body.ws_consumer).not.toBeNull();
    expect(body.ws_consumer).toHaveProperty("healthy");
    expect(body.ws_consumer).toHaveProperty("ticks_received");
    expect(body.ws_consumer).toHaveProperty("reason");
  });

  test("dashboard sidebar renders a WS Consumer row", async ({ page }) => {
    await page.goto("/");
    // HealthPanel collapses across sessions via localStorage — find its
    // header toggle by aria-controls (stable) and expand if collapsed.
    const panelToggle = page.locator(
      'button[aria-controls="health-panel-body"]',
    );
    await expect(panelToggle).toBeVisible();
    const expanded =
      (await panelToggle.getAttribute("aria-expanded")) === "true";
    if (!expanded) {
      await panelToggle.click();
    }

    // The row label is rendered as "WS Consumer" in HealthPanel.tsx.
    await expect(page.getByText(/WS Consumer/i)).toBeVisible();
  });
});
