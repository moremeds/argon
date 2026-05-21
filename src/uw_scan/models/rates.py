"""US rates mirror API contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from ._base import _UwBase, _preserve_public_module


RatesAvailability = Literal["ok", "missing", "partial", "stale"]
RatesDurationStance = Literal["BUY", "SELL", "NEUTRAL"]
RatesCurveStance = Literal["STEEP", "FLAT", "NEUTRAL"]


class RatesSummaryTile(_UwBase):
    label: str
    value: float | None = None
    unit: str = ""
    delta_1d: float | None = None
    status: RatesAvailability = "ok"


class RatesCurvePoint(_UwBase):
    tenor: str
    series_id: str
    value: float | None = None
    delta_1d_bps: float | None = None
    delta_1w_bps: float | None = None
    delta_1m_bps: float | None = None
    obs_date: date | None = None
    status: RatesAvailability = "ok"


class RatesSlopeMetric(_UwBase):
    label: str
    value_bps: float | None = None
    status: RatesAvailability = "ok"


class RatesCurveSection(_UwBase):
    points: list[RatesCurvePoint] = Field(default_factory=list)
    slopes: list[RatesSlopeMetric] = Field(default_factory=list)


class RatesDecomposition(_UwBase):
    nominal_10y: float | None = None
    real_10y: float | None = None
    breakeven_10y: float | None = None
    forward_inflation_5y5y: float | None = None
    term_forward_compensation: float | None = None
    status: RatesAvailability = "partial"


class RatesScorecardFactor(_UwBase):
    label: str
    value: str | None = None
    score: float | None = None
    status: RatesAvailability = "ok"
    source: str | None = None


class RatesScorecardGroup(_UwBase):
    id: str
    label: str
    weight: float
    score: float | None = None
    status: RatesAvailability = "ok"
    factors: list[RatesScorecardFactor] = Field(default_factory=list)


class RatesScorecard(_UwBase):
    composite_score: float | None = None
    duration_stance: RatesDurationStance = "NEUTRAL"
    curve_score: float | None = None
    curve_stance: RatesCurveStance = "NEUTRAL"
    groups: list[RatesScorecardGroup] = Field(default_factory=list)


class RatesPolicyPanel(_UwBase):
    target_range: str | None = None
    effr: float | None = None
    sofr: float | None = None
    plumbing: list[RatesSummaryTile] = Field(default_factory=list)
    status: RatesAvailability = "partial"


class RatesSupplyPanel(_UwBase):
    auctions: list[RatesSummaryTile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    status: RatesAvailability = "missing"


class RatesPositioningPanel(_UwBase):
    rows: list[RatesSummaryTile] = Field(default_factory=list)
    status: RatesAvailability = "missing"


class RatesCrossMarketPanel(_UwBase):
    rows: list[RatesSummaryTile] = Field(default_factory=list)
    status: RatesAvailability = "partial"


class RatesEventItem(_UwBase):
    event_date: date | None = None
    label: str
    importance: Literal["low", "medium", "high"] = "medium"
    source: str | None = None
    status: RatesAvailability = "missing"


class RatesSynthesisPanel(_UwBase):
    duration_view: str
    curve_view: str
    risks: list[str] = Field(default_factory=list)


class RatesSourceFreshness(_UwBase):
    id: str
    label: str
    latest_obs_date: date | None = None
    last_seen_at: datetime | None = None
    status: RatesAvailability = "missing"


class RatesSnapshotResponse(_UwBase):
    as_of: date
    computed_at: datetime
    summary: list[RatesSummaryTile] = Field(default_factory=list)
    curve: RatesCurveSection = Field(default_factory=RatesCurveSection)
    decomposition: RatesDecomposition = Field(default_factory=RatesDecomposition)
    scorecard: RatesScorecard = Field(default_factory=RatesScorecard)
    policy: RatesPolicyPanel = Field(default_factory=RatesPolicyPanel)
    supply: RatesSupplyPanel = Field(default_factory=RatesSupplyPanel)
    positioning: RatesPositioningPanel = Field(default_factory=RatesPositioningPanel)
    cross_market: RatesCrossMarketPanel = Field(default_factory=RatesCrossMarketPanel)
    events: list[RatesEventItem] = Field(default_factory=list)
    synthesis: RatesSynthesisPanel
    source_freshness: list[RatesSourceFreshness] = Field(default_factory=list)


_preserve_public_module(
    RatesSummaryTile,
    RatesCurvePoint,
    RatesSlopeMetric,
    RatesCurveSection,
    RatesDecomposition,
    RatesScorecardFactor,
    RatesScorecardGroup,
    RatesScorecard,
    RatesPolicyPanel,
    RatesSupplyPanel,
    RatesPositioningPanel,
    RatesCrossMarketPanel,
    RatesEventItem,
    RatesSynthesisPanel,
    RatesSourceFreshness,
    RatesSnapshotResponse,
)
