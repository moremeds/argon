/** @type {import('next').NextConfig} */
const nextConfig = {
  reactStrictMode: true,
  // Next 16 blocks cross-origin requests to dev resources (incl. the HMR
  // WebSocket) by default. Without this, hydration silently fails and the
  // page renders as static HTML. Add the hosts dev.sh actually serves on.
  allowedDevOrigins: ["127.0.0.1", "localhost"],
};
export default nextConfig;
