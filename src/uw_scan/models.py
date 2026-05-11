from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from enum import Enum

from pydantic import BaseModel, Field, HttpUrl


class SourceKind(str, Enum):
    UW_FLOW = "uw_flow"
    TRADINGVIEW = "tradingview"
    MANUAL = "manual"


class SignalDirection(str, Enum):
    BULLISH = "bullish"
    BEARISH = "bearish"
    NEUTRAL = "neutral"


class SourceFeed(BaseModel):
    label: str
    kind: SourceKind
    url: HttpUrl | None = None
    status: str = "ready"


class FlowRow(BaseModel):
    ticker: str
    option_symbol: str
    expiry: date
    strike: Decimal
    option_type: str
    premium: Decimal
    volume: int
    open_interest: int | None
    side: str
    dte: int
    source_label: str


class StructureIdea(BaseModel):
    structure_type: str
    rationale: str
    invalidation: str
    max_risk_note: str = "Sizing deferred"


class Opportunity(BaseModel):
    ticker: str
    contract_label: str
    direction: SignalDirection
    score: int = Field(ge=0, le=5)
    setup_types: list[str]
    confirmations: list[str]
    warnings: list[str]
    source_labels: list[str]
    structure_idea: StructureIdea | None = None


class WatchlistSourceView(BaseModel):
    source: SourceFeed
    imported_symbols: list[str]
    failed_symbols: list[str] = Field(default_factory=list)
    parsed_at_utc: datetime


class TrackedItem(BaseModel):
    label: str
    ticker: str
    option_symbol: str | None
    expiry: date | None
    tracking_kind: str
    reconciliation_status: str
    iv_change: Decimal | None = None
    oi_change: int | None = None


class SurfaceMetric(BaseModel):
    ticker: str
    expiry: date
    strike: Decimal
    call_iv: Decimal | None
    put_iv: Decimal | None
    gamma_exposure: Decimal | None
    delta_exposure: Decimal | None
    vanna_exposure: Decimal | None
    charm_exposure: Decimal | None


class KeyValueMetric(BaseModel):
    label: str
    value: str
    note: str | None = None


class ScenarioRow(BaseModel):
    tone: str
    text: str


class MarketStructureLevel(BaseModel):
    strike: str
    net_gex: str
    level: str
    key: bool = False


class MarketStructureAnalysis(BaseModel):
    score: str
    levels: list[MarketStructureLevel]
    gex_flip: str
    dealer_positioning: str
    volume_dex: str
    charm_bias: str
    vanna_bias: str


class VolatilityAnalysis(BaseModel):
    score: str
    iv_hv: str
    iv_rank: str
    iv_52w_range: str
    rv_52w_range: str
    vrp: str
    skew: str
    term_structure: str
    api_note: str


class OiChangeRow(BaseModel):
    strike: str
    call_volume: str
    put_volume: str
    note: str


class FlowPositioningAnalysis(BaseModel):
    score: str
    positioning_score: str
    net_premium: str
    bull_bear_premium: str
    call_put_ratio: str
    dark_pool: str
    top_expiries: list[str]
    short_interest: str
    oi_changes: list[OiChangeRow]
    oi_bias: str
    squeeze_risk: str
    data_note: str


class VrpAssessment(BaseModel):
    title: str
    summary: str
    metrics: list[KeyValueMetric]
    signal: str
    reason: str


class TradePlan(BaseModel):
    title: str
    structure: str
    metrics: list[KeyValueMetric]
    reasoning: str
    management_plan: list[str]


class StockAnalysis(BaseModel):
    ticker: str
    live_price: str
    signal: str
    thesis: str
    score: str
    iv_rank: str
    iv_hv: str
    skew: str
    term_structure: str
    vol_regime: str
    net_premium_1d: str
    call_put_ratio: str
    gex_flip: str
    short_interest: str
    oi_signal: str
    data_date: str
    scenarios: list[ScenarioRow]
    conviction: str
    risk: str
    watch: str
    market_structure: MarketStructureAnalysis
    volatility: VolatilityAnalysis
    flow_positioning: FlowPositioningAnalysis
    vrp_assessment: VrpAssessment
    trade_plan: TradePlan


class SnapshotSummary(BaseModel):
    run_id: str
    mode: str
    started_at_utc: datetime
    source_count: int
    opportunity_count: int


class RequestBudgetSummary(BaseModel):
    flow_rows: int
    watchlist_symbols: int
    estimated_discovery_requests: int
    estimated_enrichment_requests: int
    estimated_deep_surface_requests: int
    total_estimated_requests: int
    max_requests_per_cycle: int
    capped: bool


class DashboardViewModel(BaseModel):
    generated_at_utc: datetime
    opportunities: list[Opportunity]
    flow_rows: list[FlowRow]
    watchlist_sources: list[WatchlistSourceView]
    tracked_items: list[TrackedItem]
    surface_metrics: list[SurfaceMetric]
    stock_analyses: list[StockAnalysis] = Field(default_factory=list)
    snapshots: list[SnapshotSummary]
    request_budget: RequestBudgetSummary


def utc_now() -> datetime:
    return datetime.now(timezone.utc)


class OptionContractSnapshot(BaseModel):
    run_id: str
    option_symbol: str
    ticker: str
    market_date: date
    fetched_at_utc: datetime
    expiry: date
    strike: Decimal
    option_type: str
    implied_volatility: Decimal | None = None
    open_interest: int | None = None
    previous_open_interest: int | None = None
    volume: int | None = None
    premium: Decimal | None = None
    bid: Decimal | None = None
    ask: Decimal | None = None
    mid: Decimal | None = None


class OiByExpiryRow(BaseModel):
    run_id: str
    ticker: str
    market_date: date
    fetched_at_utc: datetime
    expiry: date
    call_open_interest: int | None = None
    put_open_interest: int | None = None
