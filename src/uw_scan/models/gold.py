"""Gold Compass API contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel

from ._base import _preserve_public_module


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
    """One declared gold input, present or explained.

    ``obs_date`` and ``as_of`` became optional so an OMISSION can be carried. They were
    required, and the router dropped any entry missing either -- so a manifest that
    recorded "this input was not read, and here is why" would have been silently
    discarded on the way to the client, reproducing the four-of-twelve manifest one layer
    up. An input with no ``omission_reason`` and no ``obs_date`` is the one shape that
    must never occur; that is a gap wearing a record's clothes.
    """

    obs_date: date | None = None
    as_of: datetime | None = None
    omission_reason: str | None = None
    lens: list[str] = []
    causal_role: str | None = None
    source: str | None = None
    row_count: int | None = None
    required: bool | None = None


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


_preserve_public_module(
    GoldGaugeState,
    GoldHistoryPoint,
    GoldCbCountryHistory,
    GoldSpotTile,
    GoldStructuralPostureModel,
    GoldTwoForceText,
    GoldCyclicalPostureModel,
    GoldValuationPostureModel,
    GoldInputProvenance,
    GoldDataFreshnessSource,
    GoldDecompositionRow,
    GoldCorrelationPoint,
    GoldCorrelationBand,
    GoldCorrelationHistory,
    GoldStateResponse,
    GoldGaugeTimeSeriesPoint,
    GoldGaugeResponse,
    GoldInputSeriesPoint,
    GoldInputSeriesResponse,
    GoldLensResponse,
)
