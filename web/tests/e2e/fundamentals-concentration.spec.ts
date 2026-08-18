import { expect, test } from "@playwright/test";
import { mkdirSync } from "node:fs";

// A browser check, not only a vitest one: esbuild and SWC disagree about JSX
// whitespace, so text that reads correctly under vitest can render with words
// run together in the real thing.
test("revenue concentration renders descriptive, with filed member strings", async ({
  page,
}) => {
  await page.goto("/stock/NVDA/fundamentals");

  const section = page.locator("section", { hasText: "Revenue concentration" });
  await expect(section).toBeVisible({ timeout: 30_000 });

  await expect(section).toContainText("descriptive · not scored");
  // Raw XBRL member strings, exactly as filed.
  await expect(section).toContainText("nvda:ComputeAndNetworkingSegmentMember");
  await expect(section).toContainText("country:US");
  // The annual periods are named, not silently filtered away.
  await expect(section).toContainText("annual periods excluded from the trend");
  await expect(section).toContainText("concentration-v1");

  mkdirSync("../output/playwright", { recursive: true });
  await section.screenshot({
    path: "../output/playwright/fundamentals-concentration-nvda.png",
  });
});
