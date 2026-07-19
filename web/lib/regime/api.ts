// URL-agnostic base. See web/lib/api.ts for rationale: browser uses a
// relative URL routed through the Next.js `/api/:path*` rewrite; server-side
// (RSC) hits FastAPI directly via the runtime NEXT_INTERNAL_API_BASE (the same
// var the rewrite proxy reads). See web/lib/api.ts + docker spec code change #7.
const API =
  typeof window !== "undefined"
    ? ""
    : (process.env.NEXT_INTERNAL_API_BASE ?? "http://127.0.0.1:8400");

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
  market_tide: (sessions: number = 5) =>
    `${API}/api/regime/market-tide?sessions=${sessions}`,
  top_net_impact: (limit: number = 40) =>
    `${API}/api/regime/top-net-impact?limit=${limit}`,
  cri_live: () => `${API}/api/regime/cri/live`,
  cri_intraday: (sessions: number = 5) =>
    `${API}/api/regime/cri/intraday?sessions=${sessions}`,
  cri_history: (days: number = 90) =>
    `${API}/api/regime/cri/history?days=${days}`,
  vcg_live: () => `${API}/api/regime/vcg/live`,
  vcg_intraday: (sessions: number = 5) =>
    `${API}/api/regime/vcg/intraday?sessions=${sessions}`,
  vcg_history: (days: number = 90) =>
    `${API}/api/regime/vcg/history?days=${days}`,
  grg: () => `${API}/api/regime/grg`,
  grg_scan: () => `${API}/api/regime/grg/scan`,
  quotes: () => `${API}/api/regime/quotes`,
  vol_backdrop: () => `${API}/api/regime/vol-backdrop`,
  dispersion: () => `${API}/api/regime/dispersion`,
  guidance: () => `${API}/api/regime/guidance`,
  validation: () => `${API}/api/regime/validation`,
  vcgValidation: () => `${API}/api/regime/vcg-validation`,
  canary: () => `${API}/api/regime/canary`,
  canaryHistory: (days: number) =>
    `${API}/api/regime/canary/history?days=${days}`,
  canaryValidation: () => `${API}/api/regime/canary/validation`,
  vrp_macro_signal: () => `${API}/api/regime/vrp-macro-signal`,
  vrp_macro_signal_live: () => `${API}/api/regime/vrp-macro-signal/live`,
  vrp_macro_entry_preview: () =>
    `${API}/api/regime/vrp-macro-signal/entry/preview`,
  vrp_macro_entry_capture: () =>
    `${API}/api/regime/vrp-macro-signal/entry/capture`,
} as const;
