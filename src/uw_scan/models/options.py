"""Option open-interest, max-pain, volume, and chain contracts."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from ._base import _UwBase


class OiPerStrikeRow(_UwBase):
    date: _date
    strike: Decimal
    call_oi: int | None = None
    put_oi: int | None = None

class OiChangeRow(_UwBase):
    underlying_symbol: str
    option_symbol: str
    curr_date: _date | None = None
    last_date: _date | None = None
    curr_oi: int | None = None
    last_oi: int | None = None
    oi_diff_plain: int | None = None
    oi_change: Decimal | None = None
    volume: int | None = None
    trades: int | None = None
    avg_price: Decimal | None = None
    last_fill: Decimal | None = None
    days_of_oi_increases: int | None = None
    days_of_vol_greater_than_oi: int | None = None
    percentage_of_total: Decimal | None = None
    rnk: int | None = None
    # Aggressor / premium breakdown — populated from UW oi-change payload.
    # See spec 2026-05-13-flow-tab-merge-design.md §4 for ASK% derivation.
    prev_ask_volume: int | None = None
    prev_bid_volume: int | None = None
    prev_mid_volume: int | None = None
    prev_neutral_volume: int | None = None
    prev_multi_leg_volume: int | None = None
    prev_stock_multi_leg_volume: int | None = None
    prev_total_premium: Decimal | None = None
    last_ask: Decimal | None = None
    last_bid: Decimal | None = None
    # Today's side breakdown — joined from option_contract_snapshots on
    # (run_id, option_symbol). The /oi-change endpoint never returns
    # prev_ask_volume etc. (all NULL), so per-contract aggressor data must
    # come from /option-contracts. The frontend uses ask vs bid to classify
    # BUY/SELL CALL/PUT intent on +ΔOI rows.
    ask_volume: int | None = None
    bid_volume: int | None = None
    mid_volume: int | None = None
    no_side_volume: int | None = None

class MaxPainRow(_UwBase):
    expiry: _date
    max_pain: Decimal | None = None
    close: Decimal | None = None
    open: Decimal | None = None
    next_upper_strike: Decimal | None = None
    next_lower_strike: Decimal | None = None

class OptionContractRow(_UwBase):
    option_symbol: str
    last_price: Decimal | None = None
    nbbo_bid: Decimal | None = None
    nbbo_ask: Decimal | None = None
    implied_volatility: Decimal | None = None
    open_interest: int | None = None
    prev_oi: int | None = None
    volume: int | None = None
    ask_volume: int | None = None
    bid_volume: int | None = None
    mid_volume: int | None = None
    multi_leg_volume: int | None = None
    stock_multi_leg_volume: int | None = None
    floor_volume: int | None = None
    sweep_volume: int | None = None
    no_side_volume: int | None = None
    avg_price: Decimal | None = None
    high_price: Decimal | None = None
    low_price: Decimal | None = None
    total_premium: Decimal | None = None

class OptionsDailyRow(_UwBase):
    """One row per trading day from UW /options-volume.

    ``bullish_premium`` here is whole-tape (UW), distinct from the
    alert-scoped :class:`FlowSnapshot.bull_premium`. Do not cross-plot.
    """

    date: _date
    call_volume: int | None = None
    put_volume: int | None = None
    call_volume_ask_side: int | None = None
    call_volume_bid_side: int | None = None
    put_volume_ask_side: int | None = None
    put_volume_bid_side: int | None = None
    call_premium: Decimal | None = None
    put_premium: Decimal | None = None
    net_call_premium: Decimal | None = None
    net_put_premium: Decimal | None = None
    bullish_premium: Decimal | None = None
    bearish_premium: Decimal | None = None
    call_open_interest: int | None = None
    put_open_interest: int | None = None
    avg_3_day_call_volume: Decimal | None = None
    avg_3_day_put_volume: Decimal | None = None
    avg_7_day_call_volume: Decimal | None = None
    avg_7_day_put_volume: Decimal | None = None
    avg_30_day_call_volume: Decimal | None = None
    avg_30_day_put_volume: Decimal | None = None

class OptionChainPerStrikeRow(_UwBase):
    """Aggregated (expiry, strike) snapshot — both volume and OI in one row.

    Backs both strike-profile charts (Volume and OI variants).
    """

    expiry: _date
    strike: Decimal
    call_volume: int | None = None
    put_volume: int | None = None
    call_oi: int | None = None
    put_oi: int | None = None
