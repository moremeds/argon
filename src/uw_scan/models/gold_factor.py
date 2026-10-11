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


_preserve_public_module(GoldFactorPoint, GoldFactorYear, GoldFactorResponse)
