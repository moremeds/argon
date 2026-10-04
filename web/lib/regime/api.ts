// Bare `/api/regime/*` paths. Every caller fetches them through
// lib/apiClient.apiFetch, which adds the browser/RSC base (I-100).
export const regimeApi = {
  cri: () => `/api/regime`,
  cri_scan: () => `/api/regime/scan`,
  vcg: () => `/api/regime/vcg`,
  vcg_scan: () => `/api/regime/vcg/scan`,
  gex: (ticker: string) =>
    `/api/regime/gex?ticker=${encodeURIComponent(ticker)}`,
  gex_intraday: (ticker: string, sessions: number = 5) =>
    `/api/regime/gex/intraday?ticker=${encodeURIComponent(ticker)}&sessions=${sessions}`,
  gex_scan: (ticker: string) =>
    `/api/regime/gex/scan?ticker=${encodeURIComponent(ticker)}`,
  market_tide: (sessions: number = 5) =>
    `/api/regime/market-tide?sessions=${sessions}`,
  top_net_impact: (limit: number = 40) =>
    `/api/regime/top-net-impact?limit=${limit}`,
  cri_live: () => `/api/regime/cri/live`,
  cri_intraday: (sessions: number = 5) =>
    `/api/regime/cri/intraday?sessions=${sessions}`,
  cri_history: (days: number = 90) =>
    `/api/regime/cri/history?days=${days}`,
  vcg_live: () => `/api/regime/vcg/live`,
  vcg_intraday: (sessions: number = 5) =>
    `/api/regime/vcg/intraday?sessions=${sessions}`,
  vcg_history: (days: number = 90) =>
    `/api/regime/vcg/history?days=${days}`,
  grg: () => `/api/regime/grg`,
  grg_scan: () => `/api/regime/grg/scan`,
  quotes: () => `/api/regime/quotes`,
  vol_backdrop: () => `/api/regime/vol-backdrop`,
  dispersion: () => `/api/regime/dispersion`,
  guidance: () => `/api/regime/guidance`,
  validation: () => `/api/regime/validation`,
  vcgValidation: () => `/api/regime/vcg-validation`,
  canary: () => `/api/regime/canary`,
  canaryHistory: (days: number) =>
    `/api/regime/canary/history?days=${days}`,
  canaryValidation: () => `/api/regime/canary/validation`,
  spx_density: () => `/api/regime/spx-density`,
  spx_density_issued: (limit: number = 5) =>
    `/api/regime/spx-density/issued?limit=${limit}`,
  vrp_macro_signal: () => `/api/regime/vrp-macro-signal`,
  vrp_macro_signal_live: () => `/api/regime/vrp-macro-signal/live`,
  vrp_macro_entry_preview: () =>
    `/api/regime/vrp-macro-signal/entry/preview`,
  vrp_macro_entry_capture: () =>
    `/api/regime/vrp-macro-signal/entry/capture`,
} as const;
