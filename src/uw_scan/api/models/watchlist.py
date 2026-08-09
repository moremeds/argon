"""Watchlist, job, and OHLC response contracts."""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Literal

from pydantic import BaseModel, Field

QueueStatusValue = Literal["queued", "running", "done", "failed"]


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


class QueueStatus(BaseModel):
    job_id: str
    status: QueueStatusValue
    queue_position: int
    requested_at: datetime
    started_at: datetime | None = None


class WatchlistCard(BaseModel):
    ticker: str
    # The single PRIMARY tag. Still decides which one section a card renders
    # under, which is why it survives alongside `chains` — grouping the grid by a
    # multi-valued field would draw NVDA's card once per chain.
    sector: str
    # Every chain this ticker belongs to (uw_scan.watchlist_chain). Filtering
    # selects on this; grouping does not. Defaults to [] so a response built
    # before the join table is seeded stays valid.
    chains: list[str] = Field(default_factory=list)
    pinned: bool
    hot: bool = False
    sort_rank: int

    spot: Decimal | None = None
    spot_quoted_at: datetime | None = None
    spot_source: str | None = None
    # Null when the ticker is in the active watchlist but no full_scan has
    # produced a card row yet — UI renders a "no data yet" placeholder.
    scanned_at: datetime | None = None

    iv_atm: Decimal | None = None
    iv_rank: Decimal | None = None
    market_cap: Decimal | None = None
    aum: Decimal | None = None

    setup: SetupBlock
    aggression_pct: Decimal | None = None
    returns: ReturnsBlock
    gamma: GammaBlock
    skew: SkewBlock
    positioning: PositioningBlock
    queue: QueueStatus | None = None


class WatchlistChainInfo(BaseModel):
    """One row of the filter rail, served rather than duplicated in TypeScript.

    The taxonomy lives in `uw_scan.watchlist_taxonomy`; hand-copying 38 chains
    into the frontend would reintroduce exactly the drift that module exists to
    prevent. `count` is live membership, so the UI can hide a chain that would
    filter to an empty grid instead of guessing.
    """

    layer: str
    layer_name: str
    focus: str
    chain: str
    count: int = 0


class WatchlistChainsResponse(BaseModel):
    chains: list[WatchlistChainInfo] = Field(default_factory=list)


class QueueSummary(BaseModel):
    total: int = 0
    queued: int = 0
    running: int = 0
    oldest_requested_at: datetime | None = None


class WatchlistResponse(BaseModel):
    scanned_at_min: datetime | None = None
    scanned_at_max: datetime | None = None
    scheduler_lag_seconds: float | None = None
    queue: QueueSummary = Field(default_factory=QueueSummary)
    # Hot-slots meter: how many tickers are flagged `hot` vs the soft cap the
    # budget governor targets. The UI shows "N / max"; flagging past max is
    # allowed but the overflow waits for budget.
    hot_count: int = 0
    hot_max: int = 0
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
    hot: bool | None = None
    sort_rank: int | None = None


class JobStatus(BaseModel):
    job_id: str
    status: QueueStatusValue
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


class WatchlistSpot(BaseModel):
    """Lightweight live-spot row for the browser poller — the WS consumer
    writes spot every ~1s; this projection avoids the full dashboard join."""

    ticker: str
    spot: Decimal | None = None
    spot_quoted_at: datetime | None = None
    spot_source: str | None = None  # "xenon_ws" | "massive.com_ws" | legacy


class WatchlistSpotsResponse(BaseModel):
    spots: list[WatchlistSpot] = Field(default_factory=list)


def _preserve_api_module(*classes: type[BaseModel]) -> None:
    for cls in classes:
        cls.__module__ = "uw_scan.api.schemas"


_preserve_api_module(
    SetupBlock,
    ReturnsBlock,
    GammaBlock,
    SkewBlock,
    PositioningBlock,
    QueueStatus,
    WatchlistCard,
    WatchlistChainInfo,
    WatchlistChainsResponse,
    QueueSummary,
    WatchlistResponse,
    WatchlistMutation,
    WatchlistPatch,
    JobStatus,
    OhlcRow,
    WatchlistSpot,
    WatchlistSpotsResponse,
)
