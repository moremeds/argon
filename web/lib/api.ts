import type { paths } from "./types";

const API = process.env.NEXT_PUBLIC_API_BASE_URL ?? "http://127.0.0.1:8400";

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
type SingleStockReport = Json<"/api/stock/{ticker}", "get">;
type StockHistoryResponse = Json<"/api/stock/{ticker}/history", "get">;
type JobStatus = Json<"/api/jobs/{job_id}", "get">;
type OhlcResponse = Json<"/api/ohlc/{ticker}", "get">;
type HealthResponse = Json<"/api/health", "get">;
type HealthSource = NonNullable<
  paths["/api/health"]["get"]["parameters"]["query"]
>["source"];
type VolatilitySeriesResponse = Json<
  "/api/stock/{ticker}/volatility/series",
  "get"
>;
type TradeInsightsResponse = Json<"/api/stock/{ticker}/trade-insights", "get">;
type TradeInsightsAiAnalysisResponse = Json<
  "/api/stock/{ticker}/trade-insights/ai-analysis",
  "post"
>;

async function _fetch<T>(path: string, init?: RequestInit): Promise<T> {
  const r = await fetch(`${API}${path}`, {
    ...init,
    headers: { "Content-Type": "application/json", ...(init?.headers ?? {}) },
    cache: "no-store",
  });
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
  stock: (ticker: string): Promise<SingleStockReport> =>
    _fetch<SingleStockReport>(`/api/stock/${ticker}`),
  stockHistory: (ticker: string): Promise<StockHistoryResponse> =>
    _fetch<StockHistoryResponse>(`/api/stock/${ticker}/history`),
  volatilitySeries: (ticker: string): Promise<VolatilitySeriesResponse> =>
    _fetch<VolatilitySeriesResponse>(`/api/stock/${ticker}/volatility/series`),
  tradeInsights: (ticker: string): Promise<TradeInsightsResponse> =>
    _fetch<TradeInsightsResponse>(`/api/stock/${ticker}/trade-insights`),
  tradeInsightsAiAnalysis: (
    ticker: string,
    body: { force_rerun?: boolean } = {},
  ): Promise<TradeInsightsAiAnalysisResponse> =>
    _fetch<TradeInsightsAiAnalysisResponse>(
      `/api/stock/${ticker}/trade-insights/ai-analysis`,
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
  ): Promise<TradeInsightsAiAnalysisResponse | null> =>
    _fetch<TradeInsightsAiAnalysisResponse | null>(
      `/api/stock/${ticker}/trade-insights/ai-analysis/latest`,
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
  health: (source: HealthSource = "uw"): Promise<HealthResponse> =>
    _fetch<HealthResponse>(`/api/health?source=${source}`),
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
      sort_rank: number;
    }>,
  ): Promise<{ ok: boolean; ticker: string }> =>
    _fetch(`/api/watchlist/${ticker}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
};

export type {
  JobStatus,
  OhlcResponse,
  SingleStockReport,
  TradeInsightsAiAnalysisResponse,
  TradeInsightsResponse,
  VolatilitySeriesResponse,
  WatchlistResponse,
};
