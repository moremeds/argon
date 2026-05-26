/**
 * Playwright config used ONLY for the canary M12 verification run.
 *
 * Points at port 3002 / 8401 — a dedicated build of THIS branch's code,
 * because the developer's running dev server on 3001/8400 is the
 * pre-canary build and lacks the new /api/regime/canary endpoints.
 *
 * Do not use this for general e2e — `playwright.config.ts` is the
 * canonical config.
 */
import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: ["canary-page.spec.ts"],
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3002",
    screenshot: "only-on-failure",
  },
});
