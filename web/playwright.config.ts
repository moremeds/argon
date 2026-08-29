import { defineConfig } from "@playwright/test";

const webPort = process.env.PLAYWRIGHT_WEB_PORT ?? "3001";
const webBaseUrl = `http://127.0.0.1:${webPort}`;

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: webBaseUrl,
    screenshot: "only-on-failure",
  },
  // /watchlist is a server component that fetches FastAPI during SSR, so the
  // API must be up before Next responds. Playwright waits for both webServer
  // entries to report healthy before starting tests.
  webServer: [
    {
      // Production start (next start) — dev mode's HMR WebSocket fails in
      // Playwright's headless Chromium and blocks React hydration.
      command: `npx next start --port ${webPort}`,
      url: webBaseUrl,
      reuseExistingServer: process.env.PLAYWRIGHT_WEB_PORT === undefined,
      timeout: 120_000,
    },
    {
      command:
        "uv run --project .. uvicorn uw_scan.api.server:app --host 127.0.0.1 --port 8400",
      url: "http://127.0.0.1:8400/api/health",
      reuseExistingServer: true,
      timeout: 60_000,
    },
  ],
});
