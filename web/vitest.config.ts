import { defineConfig } from "vitest/config";
import path from "node:path";

// Snapshots render dates; pin the zone so a UTC CI runner and an HKT laptop agree.
process.env.TZ = "UTC";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: true,
    include: ["tests/**/*.test.{ts,tsx}", "scripts/**/*.test.mjs"],
  },
  resolve: {
    alias: {
      "@": path.resolve(__dirname),
    },
  },
});
