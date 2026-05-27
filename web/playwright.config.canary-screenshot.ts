import { defineConfig } from "@playwright/test";

export default defineConfig({
  testDir: "./tests/e2e",
  testMatch: ["canary-history-screenshot.spec.ts"],
  timeout: 60_000,
  use: { baseURL: "http://127.0.0.1:3002", screenshot: "only-on-failure" },
});
