import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: /(technicals-tab|magnet-view)\.spec\.ts/,
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:13001",
    screenshot: "only-on-failure",
  },
  webServer: [
    {
      command: "node tests/e2e/technicals-fixture-server.mjs",
      url: "http://127.0.0.1:18400/health",
      reuseExistingServer: false,
      timeout: 30_000,
    },
    {
      command:
        "NEXT_INTERNAL_API_BASE=http://127.0.0.1:18400 npm run build && NEXT_INTERNAL_API_BASE=http://127.0.0.1:18400 npm run start -- --port 13001",
      url: "http://127.0.0.1:13001",
      reuseExistingServer: false,
      timeout: 120_000,
    },
  ],
});
