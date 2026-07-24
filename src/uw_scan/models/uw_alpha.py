"""UW historical-alpha row contracts (gex-levels, volatility signals, short
pressure legs, intraday flow bars, dark/lit prints).

The gex-levels and volatility/{anomaly,character,variance-risk-premium}
endpoints are real but absent from the curated UW reference — see
docs/superpowers/specs/2026-07-24-uw-historical-alpha-capture-healing-design.md
§12. Field names match the frozen fixtures in tests/fixtures/uw/.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase


class GexLevelsRow(_UwBase):
    ticker: str
    market_date: _date
    call_wall: Decimal | None = None
    put_wall: Decimal | None = None
    gamma_flip: Decimal | None = None
    gamma_magnet: Decimal | None = None
    spot: Decimal | None = None  # absent from the gex-levels payload -> stays None


class VolAnomalyRow(_UwBase):
    date: _date
    direction: str | None = None
    score: Decimal | None = None


class VolCharacterRow(_UwBase):
    date: _date
    character: str | None = None
    half_life_days: Decimal | None = None
    hurst_rv: Decimal | None = None


class VolVrpRow(_UwBase):
    date: _date
    rank: Decimal | None = None
    risk_premium: Decimal | None = None


class NetPremTickRow(_UwBase):
    # timestamp key in the payload is `tape_time`; normalizer maps it to `ts`.
    ts: datetime
    net_call_premium: Decimal | None = None
    net_put_premium: Decimal | None = None
    net_delta: Decimal | None = None
    call_volume: int | None = None
    put_volume: int | None = None


class GreekFlowRow(_UwBase):
    # timestamp key in the payload is `timestamp`; normalizer maps it to `ts`.
    ts: datetime
    dir_delta_flow: Decimal | None = None
    dir_vega_flow: Decimal | None = None
    otm_dir_delta_flow: Decimal | None = None
    otm_dir_vega_flow: Decimal | None = None
    transactions: int | None = None
    volume: int | None = None


class DarkLitPrint(_UwBase):
    # ONE model for both source='darkpool' and source='lit_flow'. NOT the existing
    # DarkPoolPrint — its sale_cond_codes is a scalar str, but this table's column
    # is TEXT[] (codex #8). All migration-108 columns are modeled (no silent loss).
    tracking_id: str  # UW ORDER-level id, NOT unique per print (child fills share it)
    ticker: str
    executed_at: datetime
    # volume = cumulative session volume at print time; the monotonic discriminator
    # that separates distinct child fills sharing a tracking_id. Part of the PK — a
    # tracking-id-only key silently collapsed 95% of lit prints (verified 2026-07-24).
    volume: int | None = None
    price: Decimal | None = None
    size: int | None = None
    premium: Decimal | None = None
    market_center: str | None = None
    nbbo_bid: Decimal | None = None
    nbbo_ask: Decimal | None = None
    nbbo_bid_quantity: int | None = None
    nbbo_ask_quantity: int | None = None
    sale_cond_codes: list[str] | None = None
    trade_code: str | None = None


class FtdRow(_UwBase):
    date: _date
    price: Decimal | None = None
    quantity: Decimal | None = None


class VolumesByExchangeRow(_UwBase):
    # One per-exchange row; the short-pressure capture sums these per date.
    date: _date
    short_volume: Decimal | None = None
    total_volume: Decimal | None = None
    short_volume_ratio: Decimal | None = None  # absent per-row; derived on aggregate


_preserve_public_module(
    GexLevelsRow,
    VolAnomalyRow,
    VolCharacterRow,
    VolVrpRow,
    NetPremTickRow,
    GreekFlowRow,
    DarkLitPrint,
    FtdRow,
    VolumesByExchangeRow,
)
