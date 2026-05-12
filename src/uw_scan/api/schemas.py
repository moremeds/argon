"""Pydantic response models — over-the-wire contract for the watchlist API.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal

from pydantic import BaseModel


class SetupBlock(BaseModel):
    type: str | None = None
    direction: str | None = None
    score: Decimal | None = None


class ReturnsBlock(BaseModel):
    """Wire shape: d1 / w1 / d30. No aliases — FastAPI would otherwise serialize
    them as JSON keys and break the frontend contract."""

    d1: Decimal | None = None
    w1: Decimal | None = None
    d30: Decimal | None = None


class GammaBlock(BaseModel):
    flip_distance: Decimal | None = None
    flip_price: Decimal | None = None
    per_1pct_move: Decimal | None = None
    max_strike: Decimal | None = None
    expiring_pct: Decimal | None = None
    expiring_date: date | None = None


class SkewBlock(BaseModel):
    rr25d_30dte: Decimal | None = None


class PositioningBlock(BaseModel):
    call_oi: int | None = None
    put_oi: int | None = None
    pcr_oi: Decimal | None = None
    pcr_vol: Decimal | None = None
    pcr_delta_30d: Decimal | None = None


class WatchlistCard(BaseModel):
    ticker: str
    sector: str
    pinned: bool
    sort_rank: int

    spot: Decimal | None = None
    spot_quoted_at: datetime | None = None
    spot_source: str | None = None
    # Null when the ticker is in the active watchlist but no full_scan has
    # produced a card row yet — UI renders a "no data yet" placeholder.
    scanned_at: datetime | None = None

    iv_atm: Decimal | None = None
    iv_rank: Decimal | None = None

    setup: SetupBlock
    aggression_pct: Decimal | None = None
    returns: ReturnsBlock
    gamma: GammaBlock
    skew: SkewBlock
    positioning: PositioningBlock


class WatchlistResponse(BaseModel):
    scanned_at_min: datetime | None = None
    scanned_at_max: datetime | None = None
    scheduler_lag_seconds: float | None = None
    tickers: list[WatchlistCard]


class WatchlistMutation(BaseModel):
    ticker: str
    sector: str
    notes: str | None = None
    pinned: bool = False
    sort_rank: int = 0


class WatchlistPatch(BaseModel):
    sector: str | None = None
    notes: str | None = None
    pinned: bool | None = None
    sort_rank: int | None = None


class JobStatus(BaseModel):
    job_id: str
    status: str
    run_id: int | None = None
    error: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None


class OhlcRow(BaseModel):
    date: date
    open: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    close: Decimal
    volume: int | None = None
