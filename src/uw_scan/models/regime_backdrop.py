"""Vol backdrop, dispersion, market tide and VRP-harvest response models.

Keep stable; update `openapi-typescript` regen when fields change.
"""

from __future__ import annotations

from datetime import date, datetime

from pydantic import BaseModel, Field, field_validator

from ._api_coerce import _to_float


class MarketTidePoint(BaseModel):
    """One 5-min market-tide bar inside a session. Premium fields are the
    market-wide net call/put premium for that bucket; `spot` is the live index
    price captured at that tick (null for backfilled history)."""

    ts: datetime
    net_call_premium: float | None = None
    net_put_premium: float | None = None
    net_volume: int | None = None
    spot: float | None = None

    _coerce_floats = field_validator(
        "net_call_premium", "net_put_premium", "spot", mode="before"
    )(_to_float)


class MarketTideSession(BaseModel):
    date: date
    points: list[MarketTidePoint] = Field(default_factory=list)


class MarketTideSentiment(BaseModel):
    """Slope/sentiment derived from the latest session's spread S = NCP − NPP.
    See reports/market_tide_sentiment.py for the math. Flow descriptor, not a
    price predictor. `trend_strength` is the divergence ratio (0..1)."""

    state: str  # BULLISH | BEARISH | BALANCED | WARMING_UP
    magnitude: str  # FLAT | LEANING | STRONG
    driver: str
    momentum: str
    spread: float | None = None
    session_slope: float | None = None  # $/hr
    recent_slope: float | None = None  # $/hr
    trend_strength: float | None = None
    volume_confirms: bool | None = None
    bars: int = 0


class MarketTideResponse(BaseModel):
    """Last N sessions of market-wide options tide for the regime Market Tide tab.

    Sessions ordered oldest→newest; points within each session ASC by ``ts``.
    Empty `sessions` is a valid response when no rows exist yet.
    """

    sessions: list[MarketTideSession] = Field(default_factory=list)
    spot_ticker: str | None = None
    as_of: datetime | None = None
    market_open: bool = False
    sentiment: MarketTideSentiment | None = None


class TopNetImpactRow(BaseModel):
    """One ticker in the market-wide net-premium ranking. `rank_change` is
    prev_rank - rank (positive = climbed since the last capture; null = new
    this session)."""

    ticker: str
    net_premium: float | None = None
    rank: int | None = None
    prev_rank: int | None = None
    rank_change: int | None = None

    _coerce_floats = field_validator("net_premium", mode="before")(_to_float)


class TopNetImpactResponse(BaseModel):
    """Top tickers by net option premium for one session (regime Market Tide
    tab, beside the daily chart). Rows sorted by net_premium DESC."""

    rows: list[TopNetImpactRow] = Field(default_factory=list)
    data_date: date | None = None


class VolBackdropPoint(BaseModel):
    date: date
    close: float


class VolBackdropResponse(BaseModel):
    """Vol-complex time series + VIX term-structure (regime page header strip)."""

    series: dict[str, list[VolBackdropPoint]] = Field(default_factory=dict)
    term_structure_ratio: float | None = None  # VIX / VIX3M, latest close
    term_structure_state: str | None = None  # "contango" | "backwardation"
    as_of: date | None = None


class DispersionResponse(BaseModel):
    """Correlation/dispersion CONTEXT for the CRI view (descriptive, NOT a signal).

    COR1M percentile is rank of the latest close within full 20yr history.
    VIX/COR1M ratio isolates the dispersion axis (high ratio ⟺ low correlation);
    its z-score is trailing-252 (strictly prior). See
    docs/research/2026-07-19-dispersion-signals-eval.md — this is regime context,
    not a validated timing signal; low correlation is NOT a warning.
    """

    as_of: date | None = None
    cor1m: float | None = None
    cor1m_percentile: float | None = None  # 0–1, fraction of 20yr history ≤ latest
    vix: float | None = None
    vix_cor1m_ratio: float | None = None
    vix_cor1m_ratio_z: float | None = None  # trailing-252
    history_start: date | None = None
    n_obs: int = 0


class VrpHarvestVerdict(BaseModel):
    """One (asset_class, deviation_class) VRP harvest bucket verdict (Spec B)."""

    asset_class: str
    deviation_class: str
    verdict: str  # "HARVEST_SELLABLE" | "NONE"
    mean_realized_vrp: float | None = None
    mean_holdout: float | None = None
    rich_cheap_spread: float | None = None
    n: int = 0
    n_holdout: int = 0
    survives_walkforward: bool = False
    survives_window_gate: bool = False
    confidence: str | None = None
    as_of: date | None = None


class VrpHarvestResponse(BaseModel):
    """VRP harvest markout verdicts — is rich vol sellable, by bucket (Spec B)."""

    verdicts: list[VrpHarvestVerdict] = Field(default_factory=list)
