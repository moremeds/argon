import type { components, paths } from "./types";

export type RadarResponse = components["schemas"]["RadarResponse"];
export type ChainMatrixResponse = components["schemas"]["ChainMatrixResponse"];
export type ChainCell = components["schemas"]["ChainCell"];
export type ChainDrilldownResponse =
  components["schemas"]["ChainDrilldownResponse"];
export type ChainMember = components["schemas"]["ChainMember"];
export type CompanyDimensionsResponse =
  components["schemas"]["CompanyDimensionsResponse"];
export type ReportResponse = components["schemas"]["ReportResponse"];
export type ReportListResponse = components["schemas"]["ReportListResponse"];
export type ResearchReportModel =
  components["schemas"]["ResearchReportModel"];
export type ReportBlock = components["schemas"]["ReportBlock"];
export type ReportDeltaModel = components["schemas"]["ReportDeltaModel"];
export type RadarRow = components["schemas"]["RadarRow"];
export type RadarDimension = components["schemas"]["RadarDimension"];
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
    : (process.env.NEXT_INTERNAL_API_BASE ?? "http://127.0.0.1:8400");

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
type WatchlistChainsResponse = Json<"/api/watchlist/chains", "get">;
// One rail row. Derived from the response rather than the component schema so
// it cannot drift from what the endpoint actually returns.
// NonNullable: `chains` has a server-side default so OpenAPI marks it optional.
type WatchlistChainInfo = NonNullable<
  WatchlistChainsResponse["chains"]
>[number];
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
export type MagnetsResponse = Json<"/api/stock/{ticker}/magnets", "get">;
type TechnicalsResponse = Json<"/api/stock/{ticker}/technicals", "get">;
export type TechnicalsLiveResponse = Json<
  "/api/stock/{ticker}/technicals/live",
  "get"
>;
export type VwapAnchorResponse = Json<
  "/api/stock/{ticker}/vwap-anchor",
  "post"
>;
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
type ScannerValueResponse = Json<"/api/scanner/value", "get">;
type ThetaHarvesterResponse = Json<"/api/scanner/theta-harvester", "get">;
type ThetaHarvesterScanResult = Json<
  "/api/scanner/theta-harvester/rescan",
  "post"
>;
type ThetaHarvesterQuoteResult = Json<
  "/api/scanner/theta-harvester/quote",
  "post"
>;
type RegimeGexResponse = Json<"/api/regime/gex", "get">;
type RegimeDealerResponse = Json<"/api/regime/dealer", "get">;
type RegimeVcgResponse = Json<"/api/regime/vcg", "get">;
type RatesSnapshotResponse = Json<"/api/rates/snapshot", "get">;
type MacroPolicyComparison = Json<"/api/macro/policy", "get">;
// All four domain states share one response model, so one alias covers the set.
type MacroDomainStateResponse = Json<"/api/macro/usd", "get">;
type MacroContextSnapshotResponse = Json<"/api/macro/snapshot", "get">;
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
  watchlistChains: (): Promise<WatchlistChainsResponse> =>
    _fetch<WatchlistChainsResponse>(`/api/watchlist/chains`),
  stock: (ticker: string): Promise<SingleStockReport> =>
    _fetch<SingleStockReport>(`/api/stock/${ticker}`),
  stockHistory: (ticker: string): Promise<StockHistoryResponse> =>
    _fetch<StockHistoryResponse>(`/api/stock/${ticker}/history`),
  volatilitySeries: (ticker: string): Promise<VolatilitySeriesResponse> =>
    _fetch<VolatilitySeriesResponse>(`/api/stock/${ticker}/volatility/series`),
  skewAnalysis: (ticker: string): Promise<SkewAnalysisResponse> =>
    _fetch<SkewAnalysisResponse>(`/api/stock/${ticker}/skew`),
  magnets: (ticker: string): Promise<MagnetsResponse> =>
    _fetch<MagnetsResponse>(`/api/stock/${ticker}/magnets`),
  fundamentals: (
    ticker: string,
  ): Promise<components["schemas"]["FundamentalCardResponse"]> =>
    _fetch(`/api/stock/${ticker}/fundamentals`),
  fundamentalStatements: (
    ticker: string,
    quarters = 20,
  ): Promise<components["schemas"]["FundamentalStatementsResponse"]> =>
    _fetch(`/api/stock/${ticker}/fundamentals/statements?quarters=${quarters}`),
  fundamentalConcentration: (
    ticker: string,
    periods = 20,
  ): Promise<components["schemas"]["FundamentalConcentrationResponse"]> =>
    _fetch(
      `/api/stock/${ticker}/fundamentals/concentration?periods=${periods}`,
    ),
  technicals: (ticker: string): Promise<TechnicalsResponse> =>
    _fetch<TechnicalsResponse>(`/api/stock/${ticker}/technicals`),
  technicalsLive: (ticker: string): Promise<TechnicalsLiveResponse> =>
    _fetch<TechnicalsLiveResponse>(`/api/stock/${ticker}/technicals/live`),
  technicalsRefresh: (ticker: string): Promise<TechnicalsResponse> =>
    _fetch<TechnicalsResponse>(`/api/stock/${ticker}/technicals/refresh`, {
      method: "POST",
    }),
  vwapAnchorSet: (
    ticker: string,
    body: { anchor_date: string },
  ): Promise<VwapAnchorResponse> =>
    _fetch<VwapAnchorResponse>(`/api/stock/${ticker}/vwap-anchor`, {
      method: "POST",
      body: JSON.stringify(body),
    }),
  vwapAnchorClear: (ticker: string): Promise<void> =>
    _fetch(`/api/stock/${ticker}/vwap-anchor`, { method: "DELETE" }),
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
  // No params by design: the list is every name in its own buy zone at the
  // latest as_of. A `sort` or `limit` would invite ordering by cheapness,
  // which measured INVERTED across names (book_to_price IC -0.0365).
  scannerValue: (): Promise<ScannerValueResponse> =>
    _fetch<ScannerValueResponse>("/api/scanner/value"),
  thetaHarvester: (
    params: URLSearchParams = new URLSearchParams(),
  ): Promise<ThetaHarvesterResponse> => {
    const q = params.toString();
    return _fetch<ThetaHarvesterResponse>(
      `/api/scanner/theta-harvester${q ? `?${q}` : ""}`,
    );
  },
  thetaHarvesterRescan: (): Promise<ThetaHarvesterScanResult> =>
    _fetch<ThetaHarvesterScanResult>("/api/scanner/theta-harvester/rescan", {
      method: "POST",
      body: JSON.stringify({}),
    }),
  // Bounded server-side at 8; a larger limit is REJECTED, not truncated.
  thetaHarvesterQuote: (limit: number): Promise<ThetaHarvesterQuoteResult> =>
    _fetch<ThetaHarvesterQuoteResult>("/api/scanner/theta-harvester/quote", {
      method: "POST",
      body: JSON.stringify({ limit }),
    }),
  positioning: (ticker: string): Promise<PositioningSnapshot> =>
    _fetch<PositioningSnapshot>(`/api/positioning/${ticker}`),
  positioningScreener: (): Promise<PositioningScreenerResponse> =>
    _fetch<PositioningScreenerResponse>(`/api/positioning/screener`),
  ratesSnapshot: (): Promise<RatesSnapshotResponse | null> =>
    _fetch<RatesSnapshotResponse | null>(`/api/rates/snapshot`, undefined, {
      allow404: true,
    }),
  // The four policy paths, each with its own publisher and release date. Kept
  // separate from ratesSnapshot deliberately: they are computed by a different
  // job on a different clock, and folding them into one call would make a stale
  // snapshot look like it carried a fresh FOMC release.
  macroPolicy: (): Promise<MacroPolicyComparison | null> =>
    _fetch<MacroPolicyComparison | null>(`/api/macro/policy`, undefined, {
      allow404: true,
    }),
  // One call per domain rather than one bundling call. The four engines run on separate
  // schedules and any of them can be absent; a bundle would make one missing state look
  // like a failed page, and the desk's whole point is saying which half is missing.
  // `allow404` is load-bearing here: a domain the pipeline has never computed 404s, and
  // that is a fact to render, not an error to throw.
  macroDomainState: (
    domain: "inflation" | "rates" | "usd" | "gold",
  ): Promise<MacroDomainStateResponse | null> =>
    _fetch<MacroDomainStateResponse | null>(`/api/macro/${domain}`, undefined, {
      allow404: true,
    }),
  // `allow404` again, and for a sharper reason than the domain reads: a 404 here means no
  // snapshot was ever assembled for the instant, which the desk must render as "nothing
  // checked whether these four belong together" -- never as a coherent chain.
  macroContextSnapshot: (
    asOfTs?: string,
  ): Promise<MacroContextSnapshotResponse | null> =>
    _fetch<MacroContextSnapshotResponse | null>(
      asOfTs
        ? `/api/macro/snapshot?as_of_ts=${encodeURIComponent(asOfTs)}`
        : "/api/macro/snapshot",
      undefined,
      { allow404: true },
    ),
  // The Radar is a read over persisted results — no provider, no lake. `state`
  // is load-bearing: an empty `rows` is six different situations and only one of
  // them is a fact about the companies.
  radar: (params?: {
    tier?: string;
    engine_version?: string;
    limit?: number;
    min_dimensions?: number;
  }): Promise<RadarResponse> => {
    const q = new URLSearchParams();
    if (params?.tier) q.set("tier", params.tier);
    if (params?.engine_version) q.set("engine_version", params.engine_version);
    if (params?.limit != null) q.set("limit", String(params.limit));
    if (params?.min_dimensions != null)
      q.set("min_dimensions", String(params.min_dimensions));
    const qs = q.toString();
    return _fetch<RadarResponse>(`/api/scanner/radar${qs ? `?${qs}` : ""}`);
  },
  chainMatrix: (params?: {
    taxonomy_version?: string;
    engine_version?: string;
    domain?: string;
  }): Promise<ChainMatrixResponse> => {
    const q = new URLSearchParams();
    if (params?.taxonomy_version) q.set("taxonomy_version", params.taxonomy_version);
    if (params?.engine_version) q.set("engine_version", params.engine_version);
    if (params?.domain) q.set("domain", params.domain);
    const qs = q.toString();
    return _fetch<ChainMatrixResponse>(
      `/api/research/chains/matrix${qs ? `?${qs}` : ""}`,
    );
  },
  chainMembers: (
    chain: string,
    params?: { layer?: string; engine_version?: string },
  ): Promise<ChainDrilldownResponse> => {
    const q = new URLSearchParams();
    if (params?.layer) q.set("layer", params.layer);
    if (params?.engine_version) q.set("engine_version", params.engine_version);
    const qs = q.toString();
    return _fetch<ChainDrilldownResponse>(
      `/api/research/chains/${encodeURIComponent(chain)}${qs ? `?${qs}` : ""}`,
    );
  },
  researchReports: (limit = 25): Promise<ReportListResponse> =>
    _fetch<ReportListResponse>(`/api/research/reports?limit=${limit}`),
  researchReport: (
    reportType: "company" | "chain",
    key: string,
    version?: number,
  ): Promise<ReportResponse> =>
    _fetch<ReportResponse>(
      `/api/research/reports/${reportType}/${encodeURIComponent(key)}` +
        (version == null ? "" : `/versions/${version}`),
    ),
  assembleResearchReport: (
    reportType: "company" | "chain",
    key: string,
    asOf?: string,
  ): Promise<ReportResponse> =>
    _fetch<ReportResponse>(
      `/api/research/reports/${reportType}/${encodeURIComponent(key)}` +
        (asOf ? `?as_of=${asOf}` : ""),
      { method: "POST" },
    ),
  companyDimensions: (
    ticker: string,
    engineVersion?: string,
  ): Promise<CompanyDimensionsResponse> =>
    _fetch<CompanyDimensionsResponse>(
      `/api/stock/${ticker}/fundamentals/dimensions${
        engineVersion ? `?engine_version=${encodeURIComponent(engineVersion)}` : ""
      }`,
    ),
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
  TechnicalsResponse,
  TradeInsightsResponse,
  VolatilitySeriesResponse,
  WatchlistChainInfo,
  WatchlistChainsResponse,
  WatchlistResponse,
};
