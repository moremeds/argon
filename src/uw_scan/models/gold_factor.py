"""Gold factor model API contracts (GET /api/gold/factor). Historical description, not a
forecast: the study's direction test failed."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import BaseModel

from ._base import _preserve_public_module

GoldFactorLabel = Literal["much", "part", "little"]


class GoldFactorPoint(BaseModel):
    obs_date: date
    b_r: float | None
    b_r_lo95: float | None
    b_r_hi95: float | None
    b_d: float | None
    b_d_lo95: float | None
    b_d_hi95: float | None
    b_s: float | None
    b_s_lo95: float | None
    b_s_hi95: float | None
    explained_share: float | None
    published_label: GoldFactorLabel | None
    gold_change: float
    own_trailing_drift: float | None
    real_yield_part: float | None
    dollar_part: float | None
    haven_part: float | None
    unexplained_1: float | None
    unexplained_21: float | None


class GoldFactorYear(BaseModel):
    """Sums over the rows of a calendar year that have every part (percent)."""

    year: int
    rows: int
    partial_year: bool
    gold_change: float
    own_trailing_drift: float
    real_yield_part: float
    dollar_part: float
    haven_part: float
    unexplained: float
    explained_share: float  # 1 - sum U^2 / sum y^2 in the year; can be negative


class GoldFactorResponse(BaseModel):
    computed_at: datetime
    last_date: date
    explained_low: float  # at or below: "little"
    explained_high: float  # at or above (with both slopes negative): "much"
    points: list[GoldFactorPoint]
    years: list[GoldFactorYear]


class DxyPoint(BaseModel):
    """Synthetic ICE dollar index; the six *_part sum to change_pct (percent, 100 x log)."""

    obs_date: date
    dxy: float
    change_pct: float | None
    eurusd_part: float | None
    usdjpy_part: float | None
    gbpusd_part: float | None
    usdcad_part: float | None
    usdsek_part: float | None
    usdchf_part: float | None


class DxyResponse(BaseModel):
    computed_at: datetime
    last_date: date
    points: list[DxyPoint]


class GoldFlowPoint(BaseModel):
    obs_date: date
    value: float


class GoldFlowsResponse(BaseModel):
    """Stored flow and holdings history, latest vintage per date. Description only."""

    china_reserves_t: list[GoldFlowPoint]  # quarterly, WGC
    cftc_mm_net_pct_oi: list[
        GoldFlowPoint
    ]  # weekly, managed-money net / open interest x 100
    lbma_vault_t: list[GoldFlowPoint]  # monthly, London vault holdings


_preserve_public_module(
    GoldFactorPoint,
    GoldFactorYear,
    GoldFactorResponse,
    DxyPoint,
    DxyResponse,
    GoldFlowPoint,
    GoldFlowsResponse,
)
