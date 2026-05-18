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
from .trade_insights import (
    CandidateStructure,
    ChainFlowReadRow,
    InsightBadge,
    InsightLeg,
    InsightsSynthesis,
    InsightSignalRow,
    SourceReconciliation,
    SourceReconciliationRow,
    TermMoveRow,
    TradeInsightsHeader,
    TradeInsightsResponse,
)
from .trade_insights_ai import (
    TradeInsightAiAnalysisRequest,
    TradeInsightAiAnalysisResponse,
    TradeInsightAiBase,
    TradeInsightAiBestExpression,
    TradeInsightAiConflict,
    TradeInsightAiDominantRead,
    TradeInsightAiGuardrails,
    TradeInsightAiHeadline,
    TradeInsightAiHighlight,
    TradeInsightAiLevel,
    TradeInsightAiMetricCard,
    TradeInsightAiOutcome,
    TradeInsightAiPreferredExpression,
    TradeInsightAiRejectedIdea,
    TradeInsightAiRendering,
    TradeInsightAiRequiredCheck,
    TradeInsightAiScenarioCard,
    TradeInsightAiScoreBreakdown,
    TradeInsightAiSectionCard,
    TradeInsightAiSectionCards,
    TradeInsightAiSnapshotMeta,
    TradeInsightAiVrpAssessment,
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


# ---------------------------------------------------------------------------
# Trade Insights AI analysis (V1.5)
# ---------------------------------------------------------------------------


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
