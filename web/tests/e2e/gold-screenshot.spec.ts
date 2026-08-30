// One-shot screenshot capture for the GOLD COMPASS page — useful for visual
// confirmation when wiring new data sources. Always passes; the artifact is
// the screenshot.
import { test } from "@playwright/test";

test("capture the macro desk's gold tab as a full-page screenshot", async ({
  page,
}) => {
  await page.setViewportSize({ width: 1440, height: 1100 });
  // Re-pointed in P6 — `/gold` 308s to the desk's tab 05. Following the redirect would
  // work, but capturing the destination directly is what makes the artifact a picture of
  // the tab rather than of a redirect that happened to land somewhere.
  await page.goto("/macro/gold", { waitUntil: "networkidle" });
  // `output/playwright/` per the repo's standing rule for browser artifacts; the path is
  // relative to `web/`, matching `chain-matrix.spec.ts`.
  await page.screenshot({
    path: "../output/playwright/macro-gold-tab.png",
    fullPage: true,
  });
});
