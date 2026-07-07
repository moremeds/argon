"""Positioning (UW `uw_positioning`) response contracts.

Surfaces the daily-banked short-interest / borrow / analyst / institutional /
insider / earnings-reaction snapshot per ticker, plus a small set of derived
signal labels (squeeze risk, insider tilt, analyst implied upside, pre-ER
reaction base rate). Read-only over the warm store — zero new UW fetch.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase


class PositioningSignals(_UwBase):
    """Derived signal labels computed at read time from the banked columns."""

    # Squeeze risk: composite of si_pct_float x days_to_cover x borrow-fee level.
    squeeze_score: int | None = None  # 0-6 (2 pts each dimension), None if all null
    squeeze_label: str = "unknown"  # HIGH | ELEVATED | LOW | unknown
    # Insider net-flow tilt (sign of insider_net_flow, UW dollar convention).
    insider_tilt: str = "unknown"  # BUYING | SELLING | NEUTRAL | unknown
    # Analyst implied upside = (target_avg - spot) / spot, percent.
    analyst_implied_upside_pct: Decimal | None = None
    # Rating skew = (buy - sell) / (buy + hold + sell), -1..+1.
    analyst_rating_skew: Decimal | None = None
    # Pre-ER positive-reaction base rate = positive / total, 0..1.
    er_positive_base_rate: Decimal | None = None
    days_to_next_er: int | None = None


class PositioningSnapshot(_UwBase):
    """Full per-ticker positioning snapshot for the stock-page card."""

    ticker: str
    available: bool = True
    snapshot_date: _date | None = None
    spot: Decimal | None = None
    # short interest + borrow
    si_pct_float: Decimal | None = None
    si_short_interest: Decimal | None = None
    si_total_float: Decimal | None = None
    si_days_to_cover: Decimal | None = None
    si_shares_available: Decimal | None = None
    si_fee_rate: Decimal | None = None
    si_rebate_rate: Decimal | None = None
    si_market_date: _date | None = None
    # analyst ratings
    analyst_buy: int | None = None
    analyst_hold: int | None = None
    analyst_sell: int | None = None
    analyst_target_avg: Decimal | None = None
    analyst_target_hi: Decimal | None = None
    analyst_target_lo: Decimal | None = None
    # institutional ownership
    inst_holder_count: int | None = None
    inst_total_value: Decimal | None = None
    # insider flow
    insider_buy_volume: Decimal | None = None
    insider_sell_volume: Decimal | None = None
    insider_net_flow: Decimal | None = None
    # earnings reactions
    earn_reactions_positive: int | None = None
    earn_reactions_total: int | None = None
    next_er_date: _date | None = None
    # derived
    signals: PositioningSignals = PositioningSignals()


class PositioningScreenerRow(_UwBase):
    """Compact per-ticker row for the watchlist positioning screener."""

    ticker: str
    snapshot_date: _date | None = None
    spot: Decimal | None = None
    si_pct_float: Decimal | None = None
    si_days_to_cover: Decimal | None = None
    si_fee_rate: Decimal | None = None
    squeeze_score: int | None = None
    squeeze_label: str = "unknown"
    insider_net_flow: Decimal | None = None
    insider_tilt: str = "unknown"
    analyst_implied_upside_pct: Decimal | None = None
    er_positive_base_rate: Decimal | None = None
    days_to_next_er: int | None = None


class PositioningScreenerResponse(_UwBase):
    rows: list[PositioningScreenerRow] = []
    generated_at: datetime
    as_of: _date | None = None


_preserve_public_module(
    PositioningSignals,
    PositioningSnapshot,
    PositioningScreenerRow,
    PositioningScreenerResponse,
)
