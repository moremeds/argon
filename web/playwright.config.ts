import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3001",
    screenshot: "only-on-failure",
  },
  // /watchlist is a server component that fetches FastAPI during SSR, so the
  // API must be up before Next responds. Playwright waits for both webServer
  // entries to report healthy before starting tests.
  webServer: [
    {
      // Production start (next start) — dev mode's HMR WebSocket fails in
      // Playwright's headless Chromium and blocks React hydration.
      command: "npm run start",
      url: "http://127.0.0.1:3001",
      reuseExistingServer: true,
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
