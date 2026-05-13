"""Typed Pydantic models for UW endpoint payloads + aggregated S1 report.

Field names mirror the actual UW payload keys verified against docs/uw-samples/*.json.
Decimal is used for prices/premiums to avoid float drift; UW returns most numerics as
strings, normalizers cast.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from pydantic import BaseModel, ConfigDict


class _UwBase(BaseModel):
    model_config = ConfigDict(extra="ignore", frozen=False)


# ---------------------------------------------------------------------------
# Flow alerts
# ---------------------------------------------------------------------------
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
    rule_id: str | None = None
    sector: str | None = None
    issue_type: str | None = None
    next_earnings_date: _date | None = None
    created_at: datetime | None = None


# ---------------------------------------------------------------------------
# Daily history rows
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Greeks / exposures (per (date, expiry, strike))
# ---------------------------------------------------------------------------
class GreekExposureRow(_UwBase):
    date: _date
    expiry: _date
    strike: Decimal
    dte: int | None = None
    call_delta: Decimal | None = None
    put_delta: Decimal | None = None
    call_gex: Decimal | None = None
    put_gex: Decimal | None = None
    call_vanna: Decimal | None = None
    put_vanna: Decimal | None = None
    call_charm: Decimal | None = None
    put_charm: Decimal | None = None


class SpotExposureRow(_UwBase):
    ticker: str
    date: _date
    expiry: _date
    strike: Decimal
    price: Decimal | None = None
    # Selective projection: take the _oi variant (per-strike open-interest weighted)
    call_delta_oi: Decimal | None = None
    put_delta_oi: Decimal | None = None
    call_gamma_oi: Decimal | None = None
    put_gamma_oi: Decimal | None = None
    call_vanna_oi: Decimal | None = None
    put_vanna_oi: Decimal | None = None
    call_charm_oi: Decimal | None = None
    put_charm_oi: Decimal | None = None


class GreeksRow(_UwBase):
    date: _date
    expiry: _date
    strike: Decimal
    call_delta: Decimal | None = None
    put_delta: Decimal | None = None
    call_gamma: Decimal | None = None
    put_gamma: Decimal | None = None
    call_vega: Decimal | None = None
    put_vega: Decimal | None = None
    call_theta: Decimal | None = None
    put_theta: Decimal | None = None
    call_rho: Decimal | None = None
    put_rho: Decimal | None = None
    call_vanna: Decimal | None = None
    put_vanna: Decimal | None = None
    call_charm: Decimal | None = None
    put_charm: Decimal | None = None
    call_volatility: Decimal | None = None
    put_volatility: Decimal | None = None
    call_option_symbol: str | None = None
    put_option_symbol: str | None = None


# ---------------------------------------------------------------------------
# OI / max pain
# ---------------------------------------------------------------------------
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


class MaxPainRow(_UwBase):
    expiry: _date
    max_pain: Decimal | None = None
    close: Decimal | None = None
    open: Decimal | None = None
    next_upper_strike: Decimal | None = None
    next_lower_strike: Decimal | None = None


# ---------------------------------------------------------------------------
# Option contracts
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Dark pool / short data
# ---------------------------------------------------------------------------
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


# ---------------------------------------------------------------------------
# Aggregates for the Single-Stock Card
# ---------------------------------------------------------------------------
class MarketStructure(_UwBase):
    spot: Decimal | None = None
    nearest_expiry: _date | None = None
    total_call_gex: Decimal | None = None
    total_put_gex: Decimal | None = None
    net_gex: Decimal | None = None
    total_call_dex_oi: Decimal | None = None
    total_put_dex_oi: Decimal | None = None
    max_pain: Decimal | None = None
    top_call_oi_strikes: list[Decimal] = []
    top_put_oi_strikes: list[Decimal] = []


class VolatilityProfile(_UwBase):
    iv: Decimal | None = None
    iv_rank: Decimal | None = None
    iv_low_52w: Decimal | None = None
    iv_high_52w: Decimal | None = None
    rv: Decimal | None = None
    rv_low_52w: Decimal | None = None
    rv_high_52w: Decimal | None = None
    iv_rank_1y: Decimal | None = None
    iv_percentile_30d: Decimal | None = None
    implied_move_30d_perc: Decimal | None = None
    skew_25d: Decimal | None = None
    term_dte_to_iv: list[tuple[int, Decimal]] = []


class FlowSnapshot(_UwBase):
    ticker: str
    flow_count: int
    net_premium: Decimal
    bull_premium: Decimal
    bear_premium: Decimal
    ask_side_premium: Decimal
    bid_side_premium: Decimal
    top_alerts: list[FlowAlert] = []


class VRPAssessment(_UwBase):
    vrp: Decimal | None = None
    signal: str
    note: str


class TradePlanLeg(_UwBase):
    option_symbol: str
    side: str  # "buy" / "sell"
    strike: Decimal
    expiry: _date
    mid: Decimal | None = None


class TradePlan(_UwBase):
    structure: str
    direction: str
    legs: list[TradePlanLeg] = []
    rationale: str
    max_loss: Decimal | None = None
    max_profit: Decimal | None = None


class SetupClassification(_UwBase):
    setup_type: str  # "C"
    label: str  # "Deep Conviction"
    direction: str  # "bull" / "bear"
    score: Decimal
    confirmations: list[str] = []
    warnings: list[str] = []
    notes: str = ""


# ---------------------------------------------------------------------------
# Bulk screener row (S2) — `/api/screener/stocks`
# ---------------------------------------------------------------------------
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


class StockHistoryRow(_UwBase):
    """One per-trading-day rollup of a ticker's market structure.

    Built from the latest successful scan_run on that date. spot comes from
    daily_ohlc.close so it's a stable end-of-day reference (NULL for the
    current trading day until the OHLC pull fires post-close).
    """

    market_date: _date
    spot: Decimal | None = None
    gex_flip: Decimal | None = None
    net_gex: Decimal | None = None
    net_dex: Decimal | None = None
    iv30d: Decimal | None = None
    pcr_vol: Decimal | None = None
    bias: str = "NEUTRAL"


class StockHistoryResponse(_UwBase):
    ticker: str
    rows: list[StockHistoryRow] = []


class SingleStockReport(_UwBase):
    run_id: int
    ticker: str
    generated_at: datetime
    short_int_note: str = "n/a (UW endpoint does not expose %)"
    market_structure: MarketStructure
    volatility: VolatilityProfile
    flow: FlowSnapshot
    vrp: VRPAssessment
    setup: SetupClassification | None = None
    trade_plan: TradePlan | None = None
    dark_pool_notional: Decimal | None = None
    dark_pool_print_count: int = 0
    short_data: ShortDataRow | None = None
    max_pain_rows: list[MaxPainRow] = []
    oi_change_top: list[OiChangeRow] = []
    aggregates: MarketAggregates | None = None
    strike_gex_curve: list[StrikeGexBucket] = []
    market_structure_levels: MarketStructureLevels | None = None
