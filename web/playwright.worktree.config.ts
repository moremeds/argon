import { defineConfig } from "@playwright/test";

// Worktree e2e config — uses servers I started manually on 3003/8403.
// Skips webServer so playwright doesn't try to spin up additional ports.
export default defineConfig({
  testDir: "./tests/e2e",
  timeout: 30_000,
  use: {
    baseURL: "http://127.0.0.1:3003",
    screenshot: "only-on-failure",
  },
});
