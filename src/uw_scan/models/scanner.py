"""Scanner and market aggregate contracts."""

from __future__ import annotations

from datetime import datetime
from datetime import date as _date
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase


class BulkScreenerRow(_UwBase):
    ticker: str
    date: _date | None = None
    sector: str | None = None
    issue_type: str | None = None
    full_name: str | None = None
    is_index: bool | None = None
    er_time: str | None = None
    next_earnings_date: _date | None = None
    next_dividend_date: _date | None = None
    marketcap: Decimal | None = None
    # Prices / volume
    close: Decimal | None = None
    prev_close: Decimal | None = None
    high: Decimal | None = None
    low: Decimal | None = None
    week_52_high: Decimal | None = None
    week_52_low: Decimal | None = None
    stock_volume: int | None = None
    avg30_volume: Decimal | None = None
    relative_volume: Decimal | None = None
    # Premiums
    call_premium: Decimal | None = None
    put_premium: Decimal | None = None
    net_call_premium: Decimal | None = None
    net_put_premium: Decimal | None = None
    bullish_premium: Decimal | None = None
    bearish_premium: Decimal | None = None
    # Flow context
    put_call_ratio: Decimal | None = None
    call_volume: int | None = None
    put_volume: int | None = None
    call_volume_ask_side: int | None = None
    call_volume_bid_side: int | None = None
    put_volume_ask_side: int | None = None
    put_volume_bid_side: int | None = None
    # OI
    call_open_interest: int | None = None
    put_open_interest: int | None = None
    total_open_interest: int | None = None
    prev_call_oi: int | None = None
    prev_put_oi: int | None = None
    # IV / vol
    iv_rank: Decimal | None = None
    iv30d: Decimal | None = None
    iv30d_1d: Decimal | None = None
    iv30d_1w: Decimal | None = None
    iv30d_1m: Decimal | None = None
    volatility: Decimal | None = None
    volatility_7: Decimal | None = None
    volatility_30: Decimal | None = None
    realized_volatility: Decimal | None = None
    variance_risk_premium: Decimal | None = None
    # Implied move
    implied_move: Decimal | None = None
    implied_move_7: Decimal | None = None
    implied_move_30: Decimal | None = None
    implied_move_perc: Decimal | None = None
    implied_move_perc_7: Decimal | None = None
    implied_move_perc_30: Decimal | None = None
    # GEX
    gex_net_change: Decimal | None = None
    gex_ratio: Decimal | None = None
    gex_perc_change: Decimal | None = None
    cum_dir_delta: int | None = None
    cum_dir_gamma: int | None = None
    cum_dir_vega: int | None = None

class EtfInfo(_UwBase):
    aum: Decimal | None = None
    name: str | None = None
    avg30_volume: Decimal | None = None
    has_options: bool | None = None

class EtfInOutflowRow(_UwBase):
    ticker: str
    date: _date
    change: Decimal | None = None
    change_prem: Decimal | None = None
    close: Decimal | None = None
    volume: Decimal | None = None
    expiration_cycle: str | None = None
    is_fomc: bool | None = None

class ScanTickerResult(_UwBase):
    """One row in the Full Scan output. Ranked by `score` desc."""

    ticker: str
    setup_type: str | None = None  # "C", "F", or None
    label: str | None = None
    direction: str | None = None
    score: Decimal = Decimal("0")
    net_premium: Decimal | None = None
    net_call_premium: Decimal | None = None
    net_put_premium: Decimal | None = None
    iv_rank: Decimal | None = None
    sector: str | None = None
    relative_volume: Decimal | None = None
    gex_net_change: Decimal | None = None
    variance_risk_premium: Decimal | None = None
    total_open_interest: int | None = None
    next_earnings_date: _date | None = None
    signals_present: list[str] = []
    confirmations: list[str] = []
    warnings: list[str] = []
    notes: str = ""
    screener_row: BulkScreenerRow | None = None

class ScanReport(_UwBase):
    run_id: int
    generated_at: datetime
    scan_date: _date | None = None
    universe_size: int
    universe_returned: int
    results: list[ScanTickerResult] = []
    dropped_tickers: list[str] = []
    top_pick: str | None = None

class MarketAggregates(_UwBase):
    """Per-ticker aggregate fields sourced from the bulk-screener endpoint.

    Populated by pipeline.run_single_stock alongside the existing per-section
    sub-models. Feeds the watchlist card POSITIONING and SKEW blocks.
    """

    call_oi_total: int | None = None
    put_oi_total: int | None = None
    call_volume_total: int | None = None
    put_volume_total: int | None = None
    call_volume_ask_side: int | None = None
    call_volume_bid_side: int | None = None
    put_volume_ask_side: int | None = None
    put_volume_bid_side: int | None = None
    pcr_oi: Decimal | None = None
    pcr_vol: Decimal | None = None
    iv30d: Decimal | None = None
    market_cap: Decimal | None = None
    aum: Decimal | None = None

class StrikeGexBucket(_UwBase):
    """One row of the per-strike, per-expiry GEX curve persisted on each scan run."""

    strike: Decimal
    expiry: _date
    net_gex: Decimal | None = None
    call_gex: Decimal | None = None
    put_gex: Decimal | None = None

class GexLevel(_UwBase):
    """One labeled level on the GEX curve (e.g. CALL WALL, PUT WALL, MAX MAGNET).

    `gamma_per_dollar` is the per-strike net_gex used as the "$N per $1" sensitivity
    figure on the tile — the dollar value of dealer hedging triggered by a $1 move.
    """

    strike: Decimal
    net_gex: Decimal | None = None
    pct_from_spot: Decimal | None = None
    gamma_per_dollar: Decimal | None = None

class MarketStructureLevels(_UwBase):
    """Derived strike-level reference points used by the Market Structure tab.

    Conventions follow FlashAlpha / SpotGamma:
      - gex_flip: lowest strike where running cumulative net_gex flips sign
      - call_wall: strike with largest call-side gamma (typically above spot)
      - put_wall: strike with largest put-side gamma magnitude (typically below spot)
      - max_magnet: strike with largest positive net_gex above spot (pulls price up)
      - second_magnet: strike with second-largest positive net_gex above spot
      - max_accel: strike with most-negative net_gex below the flip (movement accelerator)
    """

    gex_flip: GexLevel | None = None
    call_wall: GexLevel | None = None
    put_wall: GexLevel | None = None
    max_magnet: GexLevel | None = None
    second_magnet: GexLevel | None = None
    max_accel: GexLevel | None = None


_preserve_public_module(
    BulkScreenerRow,
    EtfInfo,
    EtfInOutflowRow,
    ScanTickerResult,
    ScanReport,
    MarketAggregates,
    StrikeGexBucket,
    GexLevel,
    MarketStructureLevels,
)
