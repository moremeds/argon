import { defineConfig } from "vitest/config";
import path from "node:path";

// Snapshots render dates; pin the zone so a UTC CI runner and an HKT laptop agree.
process.env.TZ = "UTC";
// Same for the default locale: an en-GB laptop renders 14:24:02 where CI's
// LANG=C (en-US) renders 2:24:02 PM.
process.env.LANG = "en_US.UTF-8";
process.env.LC_ALL = "en_US.UTF-8";

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
