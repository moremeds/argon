// URL-agnostic base. See web/lib/api.ts for rationale: browser uses a
// relative URL routed through the Next.js `/api/:path*` rewrite; server-side
// (RSC) hits FastAPI directly.
// `||` (not `??`) so an empty NEXT_PUBLIC_API_BASE_URL still falls back to
// the absolute server-side URL during RSC rendering. See web/lib/api.ts.
const API =
  typeof window !== "undefined"
    ? ""
    : process.env.NEXT_PUBLIC_API_BASE_URL || "http://127.0.0.1:8400";

export const regimeApi = {
  cri: () => `${API}/api/regime`,
  cri_scan: () => `${API}/api/regime/scan`,
  vcg: () => `${API}/api/regime/vcg`,
  vcg_scan: () => `${API}/api/regime/vcg/scan`,
  gex: (ticker: string) =>
    `${API}/api/regime/gex?ticker=${encodeURIComponent(ticker)}`,
  gex_intraday: (ticker: string, sessions: number = 5) =>
    `${API}/api/regime/gex/intraday?ticker=${encodeURIComponent(ticker)}&sessions=${sessions}`,
  gex_scan: (ticker: string) =>
    `${API}/api/regime/gex/scan?ticker=${encodeURIComponent(ticker)}`,
  vol_backdrop: () => `${API}/api/regime/vol-backdrop`,
  guidance: () => `${API}/api/regime/guidance`,
  validation: () => `${API}/api/regime/validation`,
  vcgValidation: () => `${API}/api/regime/vcg-validation`,
  canary: () => `${API}/api/regime/canary`,
  canaryHistory: (days: number) =>
    `${API}/api/regime/canary/history?days=${days}`,
  canaryValidation: () => `${API}/api/regime/canary/validation`,
} as const;
