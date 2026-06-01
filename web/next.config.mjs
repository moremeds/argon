/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
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
};
export default nextConfig;
