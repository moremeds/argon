// One-shot screenshot capture for the GOLD COMPASS page — useful for visual
// confirmation when wiring new data sources. Always passes; the artifact is
// the screenshot.
import { test } from "@playwright/test";

test("capture /gold full-page screenshot", async ({ page }) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  await page.goto("/gold", { waitUntil: "networkidle" });
  await page.screenshot({ path: "/tmp/gold-page.png", fullPage: true });
});
