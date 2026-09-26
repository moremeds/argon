import { defineConfig } from "../../web/node_modules/vitest/dist/config.js";
import { fileURLToPath } from "node:url";
const root = fileURLToPath(new URL("../../", import.meta.url));
export default defineConfig({
  root,
  cacheDir: `${root}output/profile-review/frontend/vite-cache`,
  test: { environment: "jsdom", globals: true, include: ["scripts/profile_review/frontend.test.tsx"] },
  resolve: { alias: { "@": `${root}web`, "@testing-library/react": `${root}web/node_modules/@testing-library/react`, "next/navigation": `${root}web/node_modules/next/navigation.js`, "react": `${root}web/node_modules/react`, "vitest": `${root}web/node_modules/vitest` } },
});
