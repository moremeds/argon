import { dirname, resolve } from "node:path";
import { fileURLToPath } from "node:url";

// web/ is a standalone Next project (no repo-root package.json). Next otherwise
// infers the workspace root from the nearest *ancestor* lockfile — on this Mac
// that's ~/projects/package-lock.json, which nests the standalone output under
// the full path. Pin the trace root to web/ so `output: 'standalone'` always
// emits `.next/standalone/server.js` regardless of build host / worktree depth.
const __dirname = dirname(fileURLToPath(import.meta.url));

/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Emit a self-contained server bundle (web/.next/standalone/server.js) so the
  // prod Docker image ships only the traced node_modules — no full `npm install`
  // in the runtime layer. Required by docker/web.Dockerfile.
  output: "standalone",
  outputFileTracingRoot: resolve(__dirname),
  // Next 16 blocks cross-origin requests to dev resources (incl. the HMR
  // WebSocket) by default. Without this, hydration silently fails and the
  // page renders as static HTML. Add the hosts dev.sh actually serves on.
  allowedDevOrigins: ["127.0.0.1", "localhost"],

  // URL-agnostic API proxy: client bundle calls `/api/*` (relative),
  // Next.js forwards to FastAPI at localhost:8400. Decouples the bundle
  // from any specific public hostname so the same build works under
  // Tailnet IP, Tailscale MagicDNS, Tailscale Funnel, Cloudflare Tunnel,
  // or random `trycloudflare.com` URLs — only port 3001 needs to be
  // exposed externally, since the API hop happens inside the Next.js
  // server process.
  async rewrites() {
    const upstream =
      process.env.NEXT_INTERNAL_API_BASE ?? "http://localhost:8400";
    return [
      {
        source: "/api/:path*",
        destination: `${upstream}/api/:path*`,
      },
    ];
  },

  // /rates is retired into the macro desk (docs/superpowers/plans/
  // 2026-08-27-macro-desk-page-port.md §8, P3). It lands on /macro/rates
  // rather than /macro/fed because /rates's own metadata title was "US
  // Rates Factor Desk" and its most-linked content was the traded curve —
  // the curve tab is the honest landing spot for an old link, and the Fed
  // tab is one click away in the tab bar. permanent: true so Next emits a
  // 308 (not 307) — the plan calls this out explicitly: once this redirect
  // ships, backing it out needs a second deploy, so the status code is the
  // part worth pinning in a test.
  async redirects() {
    return [
      {
        source: "/rates",
        destination: "/macro/rates",
        permanent: true,
      },
    ];
  },
};
export default nextConfig;
