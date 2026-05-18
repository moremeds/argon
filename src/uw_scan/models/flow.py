"""Flow alert, dark-pool, short-interest, and flow snapshot contracts."""

from __future__ import annotations

from datetime import datetime
from datetime import date as _date
from decimal import Decimal

from ._base import FlowFootprintLabel, _UwBase


class FlowAlert(_UwBase):
    id: str
    ticker: str
    option_chain: str | None = None
    type: str | None = None
    expiry: _date | None = None
    strike: Decimal | None = None
    price: Decimal | None = None
    underlying_price: Decimal | None = None
    total_size: int | None = None
    total_premium: Decimal | None = None
    total_ask_side_prem: Decimal | None = None
    total_bid_side_prem: Decimal | None = None
    volume: int | None = None
    open_interest: int | None = None
    volume_oi_ratio: Decimal | None = None
    has_sweep: bool | None = None
    has_floor: bool | None = None
    has_multileg: bool | None = None
    all_opening_trades: bool | None = None
    iv_start: Decimal | None = None
    iv_end: Decimal | None = None
    alert_rule: str | None = None
    flow_footprint_label: FlowFootprintLabel | None = None
    aggressor_label_confidence: Decimal | None = None
    rule_id: str | None = None
    sector: str | None = None
    issue_type: str | None = None
    next_earnings_date: _date | None = None
    created_at: datetime | None = None

class DarkPoolPrint(_UwBase):
    ticker: str
    tracking_id: int
    executed_at: datetime | None = None
    trf_executed_at: datetime | None = None
    price: Decimal | None = None
    size: int | None = None
    premium: Decimal | None = None
    nbbo_bid: Decimal | None = None
    nbbo_ask: Decimal | None = None
    nbbo_bid_quantity: int | None = None
    nbbo_ask_quantity: int | None = None
    market_center: str | None = None
    sale_cond_codes: str | None = None
    ext_hour_sold_codes: str | None = None
    trade_code: str | None = None
    trade_settlement: str | None = None
    canceled: bool | None = None

class ShortDataRow(_UwBase):
    symbol: str
    timestamp: datetime
    name: str | None = None
    short_shares_available: int | None = None
    fee_rate: Decimal | None = None
    rebate_rate: Decimal | None = None

class FlowSnapshot(_UwBase):
    ticker: str
    flow_count: int
    flow_count_is_limited: bool = False
    flow_count_30d_avg: Decimal | None = None
    flow_count_vs_30d_avg: Decimal | None = None
    flow_count_30d_days: int = 0
    top_alert_rule: str | None = None
    net_premium: Decimal
    bull_premium: Decimal
    bear_premium: Decimal
    ask_side_premium: Decimal
    bid_side_premium: Decimal
    top_alerts: list[FlowAlert] = []
