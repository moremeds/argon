import type { components, paths } from "./types";

type VrpCandidatesResponse = components["schemas"]["VrpCandidatesResponse"];
type VrpBacktestResponse = components["schemas"]["VrpBacktestResponse"];
type VrpPaperResponse = components["schemas"]["VrpPaperResponse"];
type VrpMacroPositionsResponse =
  components["schemas"]["VrpMacroPositionsResponse"];
type VrpMacroPositionDetail = components["schemas"]["VrpMacroPositionDetail"];

// URL-agnostic base. In the browser, use a relative URL so requests go back
// through whatever origin served the page (Tailnet IP, MagicDNS, Cloudflare
// Tunnel, etc.) and get proxied to FastAPI by the Next.js rewrite at
// `/api/:path*`. On the server (RSC fetches), hit FastAPI directly because
// relative URLs have no base in a Node fetch context.
// Browser: "" → relative `/api/*`, routed through the next.config.mjs rewrite.
// Server (RSC): needs an absolute URL. Read NEXT_INTERNAL_API_BASE — a *runtime*
// (non-NEXT_PUBLIC, so not build-inlined) env, the SAME var the rewrite proxy
// uses. Under launchd it's unset → localhost fallback; in Docker it's
// `http://api:8400` (the compose service), never `127.0.0.1` = the container
// itself. See docker-migration spec code change #7.
const API =
  typeof window !== "undefined"
    ? ""
    : process.env.NEXT_INTERNAL_API_BASE ?? "http://127.0.0.1:8400";

type Json<
  P extends keyof paths,
  M extends keyof paths[P],
> = paths[P][M] extends {
  responses: { 200: { content: { "application/json": infer T } } };
}
  ? T
  : paths[P][M] extends {
        responses: { 202: { content: { "application/json": infer T } } };
      }
    ? T
    : never;

type WatchlistResponse = Json<"/api/watchlist", "get">;
type QueueSummaryResponse = Json<"/api/watchlist/queue", "get">;
type WatchlistSpotsResponse = Json<"/api/watchlist/spots", "get">;
type SingleStockReport = Json<"/api/stock/{ticker}", "get">;
type StockHistoryResponse = Json<"/api/stock/{ticker}/history", "get">;
type JobStatus = Json<"/api/jobs/{job_id}", "get">;
type OhlcResponse = Json<"/api/ohlc/{ticker}", "get">;
type HealthResponse = Json<"/api/health", "get">;
type BenchmarkCurrentResponse = Json<"/api/health/benchmark/current", "get">;
type BenchmarkHistoryResponse = Json<"/api/health/benchmark/history", "get">;
type HealthSource = NonNullable<
  paths["/api/health"]["get"]["parameters"]["query"]
>["source"];
type HealthOptions = {
  recordWindowHours?: number;
  recordMinCoverage?: number;
};
type VolatilitySeriesResponse = Json<
  "/api/stock/{ticker}/volatility/series",
  "get"
>;
type SkewAnalysisResponse = Json<"/api/stock/{ticker}/skew", "get">;
type TradeInsightsResponse = Json<"/api/stock/{ticker}/trade-insights", "get">;
// Single-row response (used by GET /{analysis_id} and as the inner type of
// /latest). The OpenAPI shape lives under `paths[...]/{analysis_id}/get`.
type TradeInsightsAiAnalysisResponse = Json<
  "/api/stock/{ticker}/trade-insights/ai-analysis/{analysis_id}",
  "get"
>;
// POST returns the paired enqueue response (one stub per enabled provider).
type TradeInsightsAiAnalysisEnqueueResponse = Json<
  "/api/stock/{ticker}/trade-insights/ai-analysis",
  "post"
>;
// /latest returns a keyed pair of full analysis responses.
type TradeInsightsAiLatestPair = Json<
  "/api/stock/{ticker}/trade-insights/ai-analysis/latest",
  "get"
>;
type CockpitStateResponse = Json<"/api/cockpit/{ticker}/state", "get">;
type CockpitDealerResponse = Json<"/api/cockpit/{ticker}/dealer", "get">;
type CockpitSurfaceResponse = Json<"/api/cockpit/{ticker}/surface", "get">;
type CockpitFlowImResponse = Json<"/api/cockpit/{ticker}/flow-im", "get">;
type CockpitVrpResponse = Json<"/api/cockpit/{ticker}/vrp", "get">;
type ScannerResponse = Json<"/api/scanner", "get">;
type ScannerDiscoverResponse = Json<"/api/scanner/discover", "get">;
type RegimeGexResponse = Json<"/api/regime/gex", "get">;
type RegimeDealerResponse = Json<"/api/regime/dealer", "get">;
type RegimeVcgResponse = Json<"/api/regime/vcg", "get">;
type RatesSnapshotResponse = Json<"/api/rates/snapshot", "get">;
type PositioningSnapshot = Json<"/api/positioning/{ticker}", "get">;
type PositioningScreenerResponse = Json<"/api/positioning/screener", "get">;

async function _fetch<T>(
  path: string,
  init?: RequestInit,
  options: { allow404?: boolean } = {},
): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
  if (options.allow404 && r.status === 404) return null as T;
  if (!r.ok) {
    throw new Error(`API ${r.status} for ${path}: ${await r.text()}`);
  }
  // FastAPI returns 204 No Content with an empty body for DELETE; calling
  // r.json() on an empty body throws SyntaxError. Special-case empty.
  if (r.status === 204) return undefined as unknown as T;
  const text = await r.text();
  if (!text) return undefined as unknown as T;
  return JSON.parse(text) as T;
}

export const api = {
  watchlist: (
    params: URLSearchParams = new URLSearchParams(),
  ): Promise<WatchlistResponse> => {
    const q = params.toString();
    return _fetch<WatchlistResponse>(`/api/watchlist${q ? `?${q}` : ""}`);
  },
  queueSummary: (): Promise<QueueSummaryResponse> =>
    _fetch<QueueSummaryResponse>(`/api/watchlist/queue`),
  watchlistSpots: (): Promise<WatchlistSpotsResponse> =>
    _fetch<WatchlistSpotsResponse>(`/api/watchlist/spots`),
  stock: (ticker: string): Promise<SingleStockReport> =>
    _fetch<SingleStockReport>(`/api/stock/${ticker}`),
  stockHistory: (ticker: string): Promise<StockHistoryResponse> =>
    _fetch<StockHistoryResponse>(`/api/stock/${ticker}/history`),
  volatilitySeries: (ticker: string): Promise<VolatilitySeriesResponse> =>
    _fetch<VolatilitySeriesResponse>(`/api/stock/${ticker}/volatility/series`),
  skewAnalysis: (ticker: string): Promise<SkewAnalysisResponse> =>
    _fetch<SkewAnalysisResponse>(`/api/stock/${ticker}/skew`),
  cockpitState: (
    ticker: string,
    asof?: string,
  ): Promise<CockpitStateResponse | null> => {
    const q = asof ? `?asof=${encodeURIComponent(asof)}` : "";
    return _fetch<CockpitStateResponse | null>(
      `/api/cockpit/${ticker}/state${q}`,
      undefined,
      { allow404: true },
    );
  },
  cockpitDealer: (
    ticker: string,
    asof?: string,
  ): Promise<CockpitDealerResponse | null> => {
    const q = asof ? `?asof=${encodeURIComponent(asof)}` : "";
    return _fetch<CockpitDealerResponse | null>(
      `/api/cockpit/${ticker}/dealer${q}`,
      undefined,
      { allow404: true },
    );
  },
  cockpitSurface: (
    ticker: string,
    asof?: string,
  ): Promise<CockpitSurfaceResponse | null> => {
    const q = asof ? `?asof=${encodeURIComponent(asof)}` : "";
    return _fetch<CockpitSurfaceResponse | null>(
      `/api/cockpit/${ticker}/surface${q}`,
      undefined,
      { allow404: true },
    );
  },
  cockpitFlowIm: (
    ticker: string,
    asof?: string,
  ): Promise<CockpitFlowImResponse | null> => {
    const q = asof ? `?asof=${encodeURIComponent(asof)}` : "";
    return _fetch<CockpitFlowImResponse | null>(
      `/api/cockpit/${ticker}/flow-im${q}`,
      undefined,
      { allow404: true },
    );
  },
  cockpitVrp: (
    ticker: string,
    asof?: string,
  ): Promise<CockpitVrpResponse | null> => {
    const q = asof ? `?asof=${encodeURIComponent(asof)}` : "";
    return _fetch<CockpitVrpResponse | null>(
      `/api/cockpit/${ticker}/vrp${q}`,
      undefined,
      { allow404: true },
    );
  },
  scanner: (
    params: URLSearchParams = new URLSearchParams(),
  ): Promise<ScannerResponse> => {
    const q = params.toString();
    return _fetch<ScannerResponse>(`/api/scanner${q ? `?${q}` : ""}`);
  },
  scannerDiscover: (limit = 20): Promise<ScannerDiscoverResponse> =>
    _fetch<ScannerDiscoverResponse>(`/api/scanner/discover?limit=${limit}`),
  positioning: (ticker: string): Promise<PositioningSnapshot> =>
    _fetch<PositioningSnapshot>(`/api/positioning/${ticker}`),
  positioningScreener: (): Promise<PositioningScreenerResponse> =>
    _fetch<PositioningScreenerResponse>(`/api/positioning/screener`),
  ratesSnapshot: (): Promise<RatesSnapshotResponse | null> =>
    _fetch<RatesSnapshotResponse | null>(`/api/rates/snapshot`, undefined, {
      allow404: true,
    }),
  tradeInsights: (ticker: string): Promise<TradeInsightsResponse> =>
    _fetch<TradeInsightsResponse>(`/api/stock/${ticker}/trade-insights`),
  tradeInsightsAiAnalysis: (
    ticker: string,
    body: {
      force_rerun?: boolean;
      providers?: ("codex" | "claude" | "deepseek")[];
    } = {},
    kind: "insights" | "blast" = "insights",
  ): Promise<TradeInsightsAiAnalysisEnqueueResponse> =>
    _fetch<TradeInsightsAiAnalysisEnqueueResponse>(
      `/api/stock/${ticker}/trade-insights/ai-analysis?kind=${kind}`,
      { method: "POST", body: JSON.stringify(body) },
    ),
  tradeInsightsAiAnalysisStatus: (
    ticker: string,
    analysisId: string,
  ): Promise<TradeInsightsAiAnalysisResponse> =>
    _fetch<TradeInsightsAiAnalysisResponse>(
      `/api/stock/${ticker}/trade-insights/ai-analysis/${analysisId}`,
    ),
  tradeInsightsAiAnalysisLatest: (
    ticker: string,
    kind: "insights" | "blast" = "insights",
  ): Promise<TradeInsightsAiLatestPair> =>
    _fetch<TradeInsightsAiLatestPair>(
      `/api/stock/${ticker}/trade-insights/ai-analysis/latest?kind=${kind}`,
    ),
  ohlc: (ticker: string, days = 30): Promise<OhlcResponse> =>
    _fetch<OhlcResponse>(`/api/ohlc/${ticker}?days=${days}`),
  rescan: (ticker: string): Promise<JobStatus> =>
    _fetch<JobStatus>(`/api/watchlist/${ticker}/rescan`, { method: "POST" }),
  rescanAll: (): Promise<JobStatus[]> =>
    _fetch<JobStatus[]>(`/api/watchlist/rescan-all`, {
      method: "POST",
      body: JSON.stringify({ confirmed: true }),
    }),
  job: (jobId: string): Promise<JobStatus> =>
    _fetch<JobStatus>(`/api/jobs/${jobId}`),
  health: (
    source: HealthSource = "uw",
    options: HealthOptions = {},
    init?: RequestInit,
  ): Promise<HealthResponse> => {
    const params = new URLSearchParams({ source: source ?? "uw" });
    if (options.recordWindowHours != null) {
      params.set("record_window_hours", String(options.recordWindowHours));
    }
    if (options.recordMinCoverage != null) {
      params.set("record_min_coverage", String(options.recordMinCoverage));
    }
    return _fetch<HealthResponse>(`/api/health?${params.toString()}`, init);
  },
  healthBenchmarkCurrent: (): Promise<BenchmarkCurrentResponse> =>
    _fetch<BenchmarkCurrentResponse>("/api/health/benchmark/current"),
  healthBenchmarkHistory: (hours = 24): Promise<BenchmarkHistoryResponse> =>
    _fetch<BenchmarkHistoryResponse>(
      `/api/health/benchmark/history?hours=${hours}`,
    ),
  addTicker: (body: {
    ticker: string;
    sector: string;
    notes?: string;
    pinned?: boolean;
    sort_rank?: number;
  }): Promise<{ ok: boolean; ticker: string }> =>
    _fetch(`/api/watchlist`, { method: "POST", body: JSON.stringify(body) }),
  removeTicker: (ticker: string): Promise<void> =>
    _fetch(`/api/watchlist/${ticker}`, { method: "DELETE" }),
  patchTicker: (
    ticker: string,
    body: Partial<{
      sector: string;
      notes: string;
      pinned: boolean;
      hot: boolean;
      sort_rank: number;
    }>,
  ): Promise<{ ok: boolean; ticker: string }> =>
    _fetch(`/api/watchlist/${ticker}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  regimeGex: (ticker: string): Promise<RegimeGexResponse> =>
    _fetch<RegimeGexResponse>(
      `/api/regime/gex?ticker=${encodeURIComponent(ticker)}`,
    ),
  regimeDealer: (ticker: string): Promise<RegimeDealerResponse> =>
    _fetch<RegimeDealerResponse>(
      `/api/regime/dealer?ticker=${encodeURIComponent(ticker)}`,
    ),
  regimeVcg: (): Promise<RegimeVcgResponse> =>
    _fetch<RegimeVcgResponse>(`/api/regime/vcg`),
  vrpCandidates: (): Promise<VrpCandidatesResponse> =>
    _fetch<VrpCandidatesResponse>(`/api/vrp/candidates`),
  vrpBacktest: (holdDays?: number): Promise<VrpBacktestResponse> =>
    _fetch<VrpBacktestResponse>(
      `/api/vrp/backtest${holdDays != null ? `?hold_days=${holdDays}` : ""}`,
    ),
  vrpPaper: (): Promise<VrpPaperResponse> =>
    _fetch<VrpPaperResponse>(`/api/vrp/paper`),
  positions: (): Promise<VrpMacroPositionsResponse> =>
    _fetch<VrpMacroPositionsResponse>(`/api/positions`),
  positionDetail: (entryId: number): Promise<VrpMacroPositionDetail> =>
    _fetch<VrpMacroPositionDetail>(`/api/positions/${entryId}`),
};

export type {
  CockpitDealerResponse,
  CockpitFlowImResponse,
  JobStatus,
  CockpitStateResponse,
  CockpitSurfaceResponse,
  CockpitVrpResponse,
  BenchmarkCurrentResponse,
  BenchmarkHistoryResponse,
  OhlcResponse,
  RegimeDealerResponse,
  RegimeGexResponse,
  RegimeVcgResponse,
  RatesSnapshotResponse,
  ScannerResponse,
  SingleStockReport,
  TradeInsightsAiAnalysisEnqueueResponse,
  TradeInsightsAiAnalysisResponse,
  TradeInsightsAiLatestPair,
  SkewAnalysisResponse,
  TradeInsightsResponse,
  VolatilitySeriesResponse,
  WatchlistResponse,
};
