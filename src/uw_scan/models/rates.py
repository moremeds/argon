"""US rates mirror API contracts."""

from __future__ import annotations

from datetime import date, datetime
from typing import Literal

from pydantic import Field

from ._base import _UwBase, _preserve_public_module


RatesAvailability = Literal["ok", "missing", "partial", "stale"]
#: ``UNKNOWN`` is not a weak ``NEUTRAL``.  Neutral is a view formed from evidence;
#: unknown is the absence of enough evidence to form one, and collapsing the two is
#: what let a scorecard standing on 45% of its weight print a confident stance.
RatesDurationStance = Literal["BUY", "SELL", "NEUTRAL", "UNKNOWN"]
RatesCurveStance = Literal["STEEP", "FLAT", "NEUTRAL"]
RatesPolicyPathStance = Literal["CUT", "HOLD", "HIKE", "UNKNOWN"]


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


class RatesDecompositionAttribution(_UwBase):
    window: Literal["1D", "1W", "1M", "YTD"]
    nominal_10y_bps: float | None = None
    real_10y_bps: float | None = None
    breakeven_10y_bps: float | None = None
    residual_bps: float | None = None
    model_nominal_10y_bps: float | None = None
    expected_short_real_bps: float | None = None
    expected_short_inflation_bps: float | None = None
    real_term_premium_bps: float | None = None
    inflation_risk_premium_bps: float | None = None
    fred_model_residual_bps: float | None = None
    driver: str | None = None
    status: RatesAvailability = "partial"


class RatesDecomposition(_UwBase):
    nominal_10y: float | None = None
    real_10y: float | None = None
    breakeven_10y: float | None = None
    forward_inflation_5y5y: float | None = None
    term_forward_compensation: float | None = None
    clarida_model_date: date | None = None
    model_real_yield_10y: float | None = None
    expected_short_real_rate_10y: float | None = None
    expected_short_inflation_10y: float | None = None
    real_term_premium_10y: float | None = None
    inflation_risk_premium_10y: float | None = None
    model_nominal_10y: float | None = None
    fred_model_residual_10y: float | None = None
    model_source: str | None = None
    model_url: str | None = None
    status: RatesAvailability = "partial"
    attribution: list[RatesDecompositionAttribution] = Field(default_factory=list)


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
    duration_stance: RatesDurationStance = "UNKNOWN"
    #: Share of total group weight that actually carries a score.  The composite
    #: renormalises over surviving weight, so without this a reader cannot tell a
    #: fully-evidenced 0.4 from a 0.4 built on one group out of six.
    coverage: float | None = None
    coverage_detail: str | None = None
    curve_score: float | None = None
    curve_stance: RatesCurveStance = "NEUTRAL"
    groups: list[RatesScorecardGroup] = Field(default_factory=list)


class RatesPolicyMeeting(_UwBase):
    event_date: date | None = None
    event_end_date: date | None = None
    label: str
    action: str | None = None
    vote_split: str | None = None
    source_url: str | None = None
    status: RatesAvailability = "partial"


class RatesPolicyPathPoint(_UwBase):
    meeting_date: date
    label: str
    probability: float | None = None
    stance: RatesPolicyPathStance = "UNKNOWN"
    target_range: str | None = None
    source: str | None = None
    status: RatesAvailability = "partial"


class RatesPolicyPlumbingMetric(_UwBase):
    label: str
    value: float | None = None
    unit: str = ""
    qualifier: str | None = None
    status: RatesAvailability = "partial"


class RatesPolicyPanel(_UwBase):
    target_range: str | None = None
    target_lower: float | None = None
    target_upper: float | None = None
    effr: float | None = None
    sofr: float | None = None
    last_meeting: RatesPolicyMeeting | None = None
    implied_path: list[RatesPolicyPathPoint] = Field(default_factory=list)
    plumbing: list[RatesPolicyPlumbingMetric] = Field(default_factory=list)
    policy_read: str | None = None
    path_read: str | None = None
    plumbing_read: str | None = None
    status: RatesAvailability = "partial"


class RatesSupplyAuctionRow(_UwBase):
    cusip: str
    security_type: str
    security_term: str
    auction_date: date
    issue_date: date | None = None
    offering_amount: float | None = None
    high_rate: float | None = None
    bid_to_cover: float | None = None
    direct_bidder_pct: float | None = None
    indirect_bidder_pct: float | None = None
    primary_dealer_pct: float | None = None
    tail_indicator: str | None = None
    source_url: str | None = None
    status: RatesAvailability = "ok"


class RatesSupplyPanel(_UwBase):
    auctions: list[RatesSummaryTile] = Field(default_factory=list)
    recent_auctions: list[RatesSupplyAuctionRow] = Field(default_factory=list)
    fiscal: list[RatesSummaryTile] = Field(default_factory=list)
    notes: list[str] = Field(default_factory=list)
    supply_read: str | None = None
    status: RatesAvailability = "missing"


class RatesPositioningRow(_UwBase):
    contract_code: str
    contract_name: str
    tenor_bucket: str
    obs_date: date | None = None
    release_date: date | None = None
    open_interest: float | None = None
    dealer_net: float | None = None
    dealer_net_pct_oi: float | None = None
    asset_mgr_net: float | None = None
    asset_mgr_net_pct_oi: float | None = None
    lev_money_net: float | None = None
    lev_money_net_pct_oi: float | None = None
    source_url: str | None = None
    status: RatesAvailability = "ok"


class RatesPositioningPanel(_UwBase):
    rows: list[RatesSummaryTile] = Field(default_factory=list)
    details: list[RatesPositioningRow] = Field(default_factory=list)
    positioning_read: str | None = None
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
    RatesDecompositionAttribution,
    RatesDecomposition,
    RatesScorecardFactor,
    RatesScorecardGroup,
    RatesScorecard,
    RatesPolicyMeeting,
    RatesPolicyPathPoint,
    RatesPolicyPlumbingMetric,
    RatesPolicyPanel,
    RatesSupplyAuctionRow,
    RatesPositioningRow,
    RatesSupplyPanel,
    RatesPositioningPanel,
    RatesCrossMarketPanel,
    RatesEventItem,
    RatesSynthesisPanel,
    RatesSourceFreshness,
    RatesSnapshotResponse,
)
