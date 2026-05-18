"""Typed Pydantic models for UW endpoint payloads + aggregated S1 report.

Field names mirror the actual UW payload keys verified against docs/uw-samples/*.json.
Decimal is used for prices/premiums to avoid float drift; UW returns most numerics as
strings, normalizers cast.
"""

from __future__ import annotations

from datetime import date, datetime
from datetime import date as _date
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from ._base import (
    CharmRegime,
    FlowFootprintLabel,
    MatrixConsistencyTier,
    MatrixDirection,
    SkewRegime,
    VannaConditionalReading,
    _UwBase,
)
from .flow import (
    DarkPoolPrint,
    FlowAlert,
    FlowSnapshot,
    ShortDataRow,
)
from .greeks import GreekExposureRow, GreeksRow, SpotExposureRow
from .options import (
    MaxPainRow,
    OiChangeRow,
    OiPerStrikeRow,
    OptionChainPerStrikeRow,
    OptionContractRow,
    OptionsDailyRow,
)
from .cockpit import (
    CharmSignal,
    CockpitDealerMetrics,
    CockpitDealerPoint,
    CockpitDealerResponse,
    CockpitFlowAlert,
    CockpitFlowImResponse,
    CockpitImPoint,
    CockpitSkewPoint,
    CockpitStateResponse,
    CockpitSurfaceResponse,
    CockpitTermPoint,
    CockpitVrpPoint,
    CockpitVrpResponse,
    VannaSignal,
)
from .matrix import MatrixSourceFreshness, MatrixState, SetupClassification
from .scanner import (
    BulkScreenerRow,
    EtfInfo,
    EtfInOutflowRow,
    GexLevel,
    MarketAggregates,
    MarketStructureLevels,
    ScanReport,
    ScanTickerResult,
    StrikeGexBucket,
)
from .stock import (
    MarketStructure,
    SingleStockReport,
    StockHistoryResponse,
    StockHistoryRow,
    TradePlan,
    TradePlanLeg,
    VRPAssessment,
    VolatilityProfile,
)
from .volatility import (
    DivergencePoint,
    InterpolatedIvRow,
    IvHistogramBin,
    IvHvPoint,
    IvOfIvPoint,
    IvPercentileDistribution,
    IvRankRow,
    RealizedVolRow,
    RegimeQuadrantBlock,
    RegimeQuadrantLatest,
    RegimeQuadrantPoint,
    RvCorrPoint,
    SkewRow,
    SmileExpiryCurve,
    SmilePoint,
    TermStructureExpiryRow,
    TermStructureRow,
    VolatilitySeriesResponse,
    VolHeaderBlock,
    VolStatsRow,
    VrpDailyPoint,
)


# ---------------------------------------------------------------------------
# Flow alerts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Daily history rows
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Greeks / exposures (per (date, expiry, strike))
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# OI / max pain
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Option contracts
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Dark pool / short data
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Aggregates for the Single-Stock Card
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Bulk screener row (S2) — `/api/screener/stocks`
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# Volatility tab v2 — series response (see spec 2026-05-13)
# ---------------------------------------------------------------------------


class InsightBadge(_UwBase):
    code: str
    label: str
    severity: str = "info"


class TradeInsightsHeader(_UwBase):
    dominant_bias: str = "NEUTRAL"
    primary_setup: str = "NO_CLEAR_SETUP"
    confidence_label: str = "LOW"
    data_quality_label: str = "INSUFFICIENT"
    idea_count: int = 0
    preferred_idea_id: str | None = None
    badges: list[InsightBadge] = []


class SourceReconciliationRow(_UwBase):
    source_pair: str
    price_agreement: str = ""
    iv_agreement: str = ""
    decision: str = ""
    strike: Decimal | None = None
    source_a_call_iv: Decimal | None = None
    source_b_call_iv: Decimal | None = None
    iv_diff: Decimal | None = None


class SourceReconciliation(_UwBase):
    status: str = "UNKNOWN"
    headline: str = "Source reconciliation unavailable"
    primary_iv_source: str | None = None
    relative_shape_source: str | None = None
    rows: list[SourceReconciliationRow] = []
    decision: str = "Use deterministic data only where source agreement is understood."


class InsightSignalRow(_UwBase):
    lens: str
    read: str
    evidence: list[str] = []
    conflicts: list[str] = []


class ChainFlowReadRow(_UwBase):
    strike: Decimal
    call_volume: int | None = None
    call_open_interest: int | None = None
    put_volume: int | None = None
    put_open_interest: int | None = None
    call_put_volume_ratio: Decimal | None = None
    volume_oi_note: str = ""
    read: str = ""
    requires_t1_oi_confirmation: bool = False


class TermMoveRow(_UwBase):
    expiry: _date
    dte: int | None = None
    atm_straddle: Decimal | None = None
    implied_move_perc: Decimal | None = None
    daily_implied_move_perc: Decimal | None = None
    read: str = ""


class InsightLeg(_UwBase):
    side: str
    option_symbol: str
    option_right: str
    expiry: _date
    strike: Decimal
    mid: Decimal | None = None


class CandidateStructure(_UwBase):
    idea_id: str
    structure: str
    thesis: str
    expression_type: str
    legs: list[InsightLeg] = []
    net_credit_debit: Decimal | None = None
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakevens: list[Decimal] = []
    profit_zone: str = ""
    edge_source: str = ""
    risk_flags: list[str] = []
    rank: int
    status: str = "candidate"


class InsightsSynthesis(_UwBase):
    dominant_story: str = ""
    preferred_idea_id: str | None = None
    best_risk_reward_idea_id: str | None = None
    avoid: list[str] = []
    required_before_sizing: list[str] = []


class TradeInsightsResponse(_UwBase):
    ticker: str
    as_of: datetime | None = None
    mode: str = "research"
    header: TradeInsightsHeader
    source_reconciliation: SourceReconciliation = SourceReconciliation()
    signal_stack: list[InsightSignalRow] = []
    flow_table: list[ChainFlowReadRow] = []
    term_structure_table: list[TermMoveRow] = []
    candidate_structures: list[CandidateStructure] = []
    synthesis: InsightsSynthesis = InsightsSynthesis()


# ---------------------------------------------------------------------------
# Trade Insights AI analysis (V1.5)
# ---------------------------------------------------------------------------
class TradeInsightAiBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class TradeInsightAiDominantRead(TradeInsightAiBase):
    headline: str
    summary: str
    confidence_commentary: str
    data_quality_commentary: str


class TradeInsightAiSnapshotMeta(TradeInsightAiBase):
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    data_as_of: str | None = None
    freshness_label: str = "unknown"
    source_notes: list[str] = Field(default_factory=list)


class TradeInsightAiHeadline(TradeInsightAiBase):
    title: str
    stance: Literal["bullish", "bearish", "neutral", "mixed", "wait"]
    stance_label: str
    score: int
    score_scale: int = 100
    conviction: str
    conviction_label: str
    top_reason: str
    primary_risk: str
    watch_trigger: str


class TradeInsightAiMetricCard(TradeInsightAiBase):
    label: str
    value: str
    tone: str = "neutral"
    source_path: str | None = None
    note: str = ""


class TradeInsightAiScenarioCard(TradeInsightAiBase):
    case: Literal["upside", "base", "downside"] | str
    tone: str = "neutral"
    title: str
    description: str


class TradeInsightAiScoreBreakdown(TradeInsightAiBase):
    section: str
    score: int
    max_score: int
    summary: str


class TradeInsightAiHighlight(TradeInsightAiBase):
    label: str
    value: str
    source_path: str | None = None
    note: str = ""


class TradeInsightAiLevel(TradeInsightAiBase):
    price: str
    kind: str
    value: str
    importance: str = "normal"
    source_path: str | None = None
    note: str = ""


class TradeInsightAiSectionCard(TradeInsightAiBase):
    title: str
    score: int | None = None
    max_score: int | None = None
    summary: str
    highlights: list[TradeInsightAiHighlight] = Field(default_factory=list)
    levels: list[TradeInsightAiLevel] = Field(default_factory=list)
    data_quality: str = "unknown"


class TradeInsightAiSectionCards(TradeInsightAiBase):
    market_structure: TradeInsightAiSectionCard
    volatility: TradeInsightAiSectionCard
    flow_positioning: TradeInsightAiSectionCard


class TradeInsightAiVrpAssessment(TradeInsightAiBase):
    signal: str
    title: str
    summary: str
    metrics: list[TradeInsightAiMetricCard] = Field(default_factory=list)
    reason: str


class TradeInsightAiPreferredExpression(TradeInsightAiBase):
    idea_id: str
    structure: str
    title: str
    subtitle: str = ""
    estimated_entry: str = ""
    max_profit_observed: str = ""
    max_loss_observed: str = ""
    reward_risk: str = ""
    why: str
    management_notes: list[str] = Field(default_factory=list)
    status_observed: str
    risk_flags_observed: list[str] = Field(default_factory=list)


class TradeInsightAiBestExpression(TradeInsightAiBase):
    idea_id: str
    structure: str
    role: str
    why: str
    caveats: list[str] = Field(default_factory=list)
    status_observed: str
    risk_flags_observed: list[str] = Field(default_factory=list)


class TradeInsightAiConflict(TradeInsightAiBase):
    lens: str
    severity: str
    description: str
    affected_idea_ids: list[str] = Field(default_factory=list)


class TradeInsightAiRequiredCheck(TradeInsightAiBase):
    check: str
    reason: str
    blocks_sizing: bool = True
    source: str = ""


class TradeInsightAiRejectedIdea(TradeInsightAiBase):
    idea_id: str
    structure: str
    reason: str


class TradeInsightAiRendering(TradeInsightAiBase):
    disclaimer: str
    card_order: list[str] = Field(default_factory=list)


class TradeInsightAiGuardrails(TradeInsightAiBase):
    statuses_preserved: bool
    risk_flags_preserved: bool
    no_executable_recommendations: bool


class TradeInsightAiOutcome(TradeInsightAiBase):
    schema_version: str
    analysis_produced_at: datetime
    ticker: str
    underlying_price: str | None = None
    snapshot: TradeInsightAiSnapshotMeta
    headline: TradeInsightAiHeadline
    metric_cards: list[TradeInsightAiMetricCard]
    scenario_cards: list[TradeInsightAiScenarioCard]
    score_breakdown: list[TradeInsightAiScoreBreakdown]
    section_cards: TradeInsightAiSectionCards
    vrp_assessment: TradeInsightAiVrpAssessment | None = None
    preferred_expression: TradeInsightAiPreferredExpression | None = None
    dominant_read: TradeInsightAiDominantRead
    best_expressions: list[TradeInsightAiBestExpression] = Field(default_factory=list)
    conflicts: list[TradeInsightAiConflict] = Field(default_factory=list)
    required_checks: list[TradeInsightAiRequiredCheck] = Field(default_factory=list)
    rejected_ideas: list[TradeInsightAiRejectedIdea] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    rendering: TradeInsightAiRendering
    guardrails: TradeInsightAiGuardrails


class TradeInsightAiAnalysisRequest(TradeInsightAiBase):
    force_rerun: bool = False


class TradeInsightAiAnalysisResponse(TradeInsightAiBase):
    analysis_id: UUID
    ticker: str
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    model: str
    prompt_version: str
    status: Literal["queued", "running", "succeeded", "failed"]
    produced_at: datetime | None = None
    outcome: TradeInsightAiOutcome | None = None
    markdown: str | None = None
    error_message: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reused: bool = False


# ---------------------------------------------------------------------------
# Gold endpoint (Phase A1) — GOLD COMPASS response models
# ---------------------------------------------------------------------------

PostureChipState = Literal["FAVORABLE", "NEUTRAL", "STRETCHED", "SUSPENDED", "DEGRADED"]


class GoldGaugeState(BaseModel):
    corr_60d: Decimal | None = None
    corr_126d: Decimal | None = None
    corr_252d: Decimal | None = None
    corr_504d: Decimal | None = None
    corr_252d_returns: Decimal | None = None
    state: Literal["operative", "partial", "suspended"]


class GoldHistoryPoint(BaseModel):
    obs_date: date
    value: Decimal


class GoldCbCountryHistory(BaseModel):
    country_iso3: str
    country_name: str
    bucket: str
    latest_reserves_t: Decimal | None = None
    history: list[GoldHistoryPoint] = []


class GoldSpotTile(BaseModel):
    """XAU/USD snapshot used by the Tier 1 KPI strip."""

    last: Decimal
    delta_abs: Decimal
    delta_pct: Decimal
    high: Decimal
    low: Decimal
    open: Decimal


class GoldStructuralPostureModel(BaseModel):
    state_label: str | None = None
    posture_chip: PostureChipState
    cb_strategic_12m_sum_t: Decimal | None = None
    cb_tactical_12m_sum_t: Decimal | None = None
    cb_diversifier_12m_sum_t: Decimal | None = None
    cb_52w_pct: Decimal | None = None
    gld_holdings_t: Decimal | None = None
    gld_30d_net_flow_t: Decimal | None = None
    comex_registered_oz: Decimal | None = None
    comex_20d_roc_pct: Decimal | None = None
    lbma_30d_momentum_t: Decimal | None = None
    cot_mm_net_pct: Decimal | None = None
    cot_mm_4w_change_sigma: Decimal | None = None
    uw_25d_skew_sigma: Decimal | None = None
    fx_basket_dxy_z: Decimal | None = None
    xau_cny_premium_pct: Decimal | None = None
    gld_history: list[GoldHistoryPoint] = []
    gold_history: list[GoldHistoryPoint] = []
    cb_country_history: list[GoldCbCountryHistory] = []
    narrative_text: str


class GoldTwoForceText(BaseModel):
    discount_rate: str
    hedge_demand: str


class GoldCyclicalPostureModel(BaseModel):
    zone_label: str | None = None
    posture_chip: PostureChipState
    cpi_yoy: Decimal | None = None
    t5yifr: Decimal | None = None
    t5yifr_pct_52w: Decimal | None = None
    dfii10: Decimal | None = None
    dfii10_60d_change_bps: Decimal | None = None
    dxy: Decimal | None = None
    dxy_60d_sigma: Decimal | None = None
    gpr_value: Decimal | None = None
    gpr_pct_52w: Decimal | None = None
    factors: dict[str, float] = {}
    two_force_text: GoldTwoForceText
    narrative_text: str


class GoldValuationPostureModel(BaseModel):
    flag: Literal["Low", "Moderate", "High", "Severe"]
    posture_chip: PostureChipState
    real_price_percentile: Decimal | None = None
    gold_m2_ratio_percentile: Decimal | None = None
    gold_oil_ratio_percentile: Decimal | None = None
    gold_spx_ratio_percentile: Decimal | None = None
    narrative_text: str


class GoldInputProvenance(BaseModel):
    obs_date: date
    as_of: datetime


class GoldDataFreshnessSource(BaseModel):
    """Per-source freshness for the Tier 1 Data Freshness card."""

    id: str
    last_as_of: datetime | None = None
    stale_seconds: int | None = None
    status: Literal["ok", "missing"] = "ok"


class GoldDecompositionRow(BaseModel):
    """One row of the Tier 5 lens-decomposition bars."""

    lens: Literal["L1", "L2", "L3"]
    factor: str
    contribution: Decimal


class GoldCorrelationPoint(BaseModel):
    obs_date: date
    value: Decimal


class GoldCorrelationBand(BaseModel):
    mean: Decimal
    std: Decimal


class GoldCorrelationHistory(BaseModel):
    """Tier 5 correlation-history panel inputs."""

    gold_dfii10: list[GoldCorrelationPoint] = []
    gold_dxy: list[GoldCorrelationPoint] = []
    gold_gpr: list[GoldCorrelationPoint] = []
    pre_2022_band: GoldCorrelationBand | None = None


class GoldStateResponse(BaseModel):
    obs_date: date
    computed_at: datetime
    gauge: GoldGaugeState
    spot: GoldSpotTile
    structural: GoldStructuralPostureModel
    cyclical: GoldCyclicalPostureModel
    valuation: GoldValuationPostureModel
    inputs_used: dict[str, GoldInputProvenance]
    data_freshness: list[GoldDataFreshnessSource] = []
    decomposition_rows: list[GoldDecompositionRow] = []
    correlation_history: GoldCorrelationHistory = GoldCorrelationHistory()


class GoldGaugeTimeSeriesPoint(BaseModel):
    obs_date: date
    corr_252d: Decimal | None


class GoldGaugeResponse(BaseModel):
    current: GoldGaugeState
    history_252d: list[GoldGaugeTimeSeriesPoint]


class GoldInputSeriesPoint(BaseModel):
    obs_date: date
    value: Decimal
    as_of: datetime
    release_date: date | None = None


class GoldInputSeriesResponse(BaseModel):
    series_id: str
    points: list[GoldInputSeriesPoint]


class GoldLensResponse(BaseModel):
    """Detail payload for one lens (richer than the summary in GoldStateResponse)."""

    lens_id: Literal["structural", "cyclical", "valuation"]
    posture: (
        GoldStructuralPostureModel
        | GoldCyclicalPostureModel
        | GoldValuationPostureModel
    )
    detail: dict[str, list[GoldInputSeriesPoint]]
