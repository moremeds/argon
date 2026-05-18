"""Volatility source rows and series response contracts."""

from __future__ import annotations

from datetime import datetime
from datetime import date as _date
from decimal import Decimal

from ._base import _UwBase, _preserve_public_module


class IvRankRow(_UwBase):
    date: _date
    close: Decimal | None = None
    volatility: Decimal | None = None
    iv_rank_1y: Decimal | None = None
    updated_at: datetime | None = None

class VolStatsRow(_UwBase):
    ticker: str
    date: _date
    iv: Decimal | None = None
    iv_low: Decimal | None = None
    iv_high: Decimal | None = None
    iv_rank: Decimal | None = None
    rv: Decimal | None = None
    rv_low: Decimal | None = None
    rv_high: Decimal | None = None

class RealizedVolRow(_UwBase):
    date: _date
    price: Decimal | None = None
    implied_volatility: Decimal | None = None
    realized_volatility: Decimal | None = None
    unshifted_rv_date: _date | None = None

class TermStructureRow(_UwBase):
    ticker: str
    date: _date
    expiry: _date
    dte: int | None = None
    volatility: Decimal | None = None
    implied_move: Decimal | None = None
    implied_move_perc: Decimal | None = None

class InterpolatedIvRow(_UwBase):
    date: _date
    days: int
    percentile: Decimal | None = None
    volatility: Decimal | None = None
    implied_move_perc: Decimal | None = None

class SkewRow(_UwBase):
    ticker: str
    date: _date
    delta: int
    risk_reversal: Decimal | None = None
    expiry: _date | None = None

class VolHeaderBlock(_UwBase):
    iv: Decimal | None = None
    rv: Decimal | None = None
    iv_rank: Decimal | None = None
    iv_rank_1y: Decimal | None = None
    iv_low_52w: Decimal | None = None
    iv_high_52w: Decimal | None = None
    rv_low_52w: Decimal | None = None
    rv_high_52w: Decimal | None = None
    iv_percentile_30d: Decimal | None = None
    implied_move_30d_perc: Decimal | None = None
    skew_25d: Decimal | None = None
    vrp: Decimal | None = None
    vrp_signal: str = ""
    vrp_note: str = ""

class TermStructureExpiryRow(_UwBase):
    expiry: _date
    dte: int | None = None
    by_strike: dict[str, Decimal] = {}
    strikes: dict[str, Decimal] = {}

class SmilePoint(_UwBase):
    strike: Decimal
    iv: Decimal | None = None

class SmileExpiryCurve(_UwBase):
    expiry: _date
    points: list[SmilePoint] = []

class IvHvPoint(_UwBase):
    date: _date
    iv: Decimal | None = None
    rv: Decimal | None = None

class IvHistogramBin(_UwBase):
    lo: Decimal
    hi: Decimal
    count: int

class IvPercentileDistribution(_UwBase):
    bins: list[IvHistogramBin] = []
    current_iv: Decimal | None = None
    current_pctile: Decimal | None = None

class IvOfIvPoint(_UwBase):
    date: _date
    iv: Decimal | None = None
    iv_of_iv_20: Decimal | None = None

class RvCorrPoint(_UwBase):
    date: _date
    rv: Decimal | None = None
    spy_corr_21: Decimal | None = None

class RegimeQuadrantPoint(_UwBase):
    date: _date
    rvol_pctile: Decimal | None = None
    spy_corr_21: Decimal | None = None

class RegimeQuadrantLatest(_UwBase):
    date: _date
    rvol_pctile: Decimal | None = None
    spy_corr_21: Decimal | None = None
    state: str = ""

class RegimeQuadrantBlock(_UwBase):
    points: list[RegimeQuadrantPoint] = []
    latest: RegimeQuadrantLatest | None = None
    cutoff_corr: Decimal | None = None

class DivergencePoint(_UwBase):
    date: _date
    iv_z: Decimal | None = None
    rv_z: Decimal | None = None

class VrpDailyPoint(_UwBase):
    date: _date
    vrp: Decimal | None = None
    vrp_z_20: Decimal | None = None

class VolatilitySeriesResponse(_UwBase):
    ticker: str
    as_of: _date
    backfill_status: str
    header: VolHeaderBlock
    term_structure: list[TermStructureExpiryRow] = []
    smile: list[SmileExpiryCurve] = []
    hv_iv_history: list[IvHvPoint] = []
    iv_percentile_distribution: IvPercentileDistribution = IvPercentileDistribution()
    iv_of_iv: list[IvOfIvPoint] = []
    rv_spy_corr: list[RvCorrPoint] = []
    regime_quadrant: RegimeQuadrantBlock = RegimeQuadrantBlock()
    divergence: list[DivergencePoint] = []
    divergence_headline: str = ""
    vrp_spread: list[VrpDailyPoint] = []
    vrp_spread_headline: str = ""
    spot: Decimal | None = None


_preserve_public_module(
    IvRankRow,
    VolStatsRow,
    RealizedVolRow,
    TermStructureRow,
    InterpolatedIvRow,
    SkewRow,
    VolHeaderBlock,
    TermStructureExpiryRow,
    SmilePoint,
    SmileExpiryCurve,
    IvHvPoint,
    IvHistogramBin,
    IvPercentileDistribution,
    IvOfIvPoint,
    RvCorrPoint,
    RegimeQuadrantPoint,
    RegimeQuadrantLatest,
    RegimeQuadrantBlock,
    DivergencePoint,
    VrpDailyPoint,
    VolatilitySeriesResponse,
)
