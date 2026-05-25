const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400";

export const regimeApi = {
  cri: () => `${API}/api/regime`,
  cri_scan: () => `${API}/api/regime/scan`,
  vcg: () => `${API}/api/regime/vcg`,
  vcg_scan: () => `${API}/api/regime/vcg/scan`,
  gex: (ticker: string) =>
    `${API}/api/regime/gex?ticker=${encodeURIComponent(ticker)}`,
  gex_scan: (ticker: string) =>
    `${API}/api/regime/gex/scan?ticker=${encodeURIComponent(ticker)}`,
  vol_backdrop: () => `${API}/api/regime/vol-backdrop`,
  guidance: () => `${API}/api/regime/guidance`,
  validation: () => `${API}/api/regime/validation`,
  vcgValidation: () => `${API}/api/regime/vcg-validation`,
} as const;
