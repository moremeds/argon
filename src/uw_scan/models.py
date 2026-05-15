"""Typed Pydantic models for UW endpoint payloads + aggregated S1 report.

Field names mirror the actual UW payload keys verified against docs/uw-samples/*.json.
Decimal is used for prices/premiums to avoid float drift; UW returns most numerics as
strings, normalizers cast.
"""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field


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


class EtfInfo(_UwBase):
    aum: Decimal | None = None
    name: str | None = None
    avg30_volume: Decimal | None = None
    has_options: bool | None = None


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
    spot_quoted_at: datetime | None = None
    spot_source: str | None = None
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
    options_timeline: list[OptionsDailyRow] = []
    option_chain_per_strike: list[OptionChainPerStrikeRow] = []
    # Promoted from FlowAlert.next_earnings_date so the Volume-timeline panel
    # can render the earnings marker without iterating alerts on the client.
    next_earnings_date: _date | None = None


# ---------------------------------------------------------------------------
# Volatility tab v2 — series response (see spec 2026-05-13)
# ---------------------------------------------------------------------------
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


class InsightBadge(_UwBase):
    code: str
    label: str
    severity: str = "info"


class TradeInsightsHeader(_UwBase):
    dominant_bias: str = "NEUTRAL"
    primary_setup: str = "NO_CLEAR_SETUP"
    confidence_label: str = "LOW"
    data_quality_label: str = "INSUFFICIENT"
    idea_count: int = 0
    preferred_idea_id: str | None = None
    badges: list[InsightBadge] = []


class SourceReconciliationRow(_UwBase):
    source_pair: str
    price_agreement: str = ""
    iv_agreement: str = ""
    decision: str = ""
    strike: Decimal | None = None
    source_a_call_iv: Decimal | None = None
    source_b_call_iv: Decimal | None = None
    iv_diff: Decimal | None = None


class SourceReconciliation(_UwBase):
    status: str = "UNKNOWN"
    headline: str = "Source reconciliation unavailable"
    primary_iv_source: str | None = None
    relative_shape_source: str | None = None
    rows: list[SourceReconciliationRow] = []
    decision: str = "Use deterministic data only where source agreement is understood."


class InsightSignalRow(_UwBase):
    lens: str
    read: str
    evidence: list[str] = []
    conflicts: list[str] = []


class ChainFlowReadRow(_UwBase):
    strike: Decimal
    call_volume: int | None = None
    call_open_interest: int | None = None
    put_volume: int | None = None
    put_open_interest: int | None = None
    call_put_volume_ratio: Decimal | None = None
    volume_oi_note: str = ""
    read: str = ""
    requires_t1_oi_confirmation: bool = False


class TermMoveRow(_UwBase):
    expiry: _date
    dte: int | None = None
    atm_straddle: Decimal | None = None
    implied_move_perc: Decimal | None = None
    daily_implied_move_perc: Decimal | None = None
    read: str = ""


class InsightLeg(_UwBase):
    side: str
    option_symbol: str
    option_right: str
    expiry: _date
    strike: Decimal
    mid: Decimal | None = None


class CandidateStructure(_UwBase):
    idea_id: str
    structure: str
    thesis: str
    expression_type: str
    legs: list[InsightLeg] = []
    net_credit_debit: Decimal | None = None
    max_profit: Decimal | None = None
    max_loss: Decimal | None = None
    breakevens: list[Decimal] = []
    profit_zone: str = ""
    edge_source: str = ""
    risk_flags: list[str] = []
    rank: int
    status: str = "candidate"


class InsightsSynthesis(_UwBase):
    dominant_story: str = ""
    preferred_idea_id: str | None = None
    best_risk_reward_idea_id: str | None = None
    avoid: list[str] = []
    required_before_sizing: list[str] = []


class TradeInsightsResponse(_UwBase):
    ticker: str
    as_of: datetime | None = None
    mode: str = "research"
    header: TradeInsightsHeader
    source_reconciliation: SourceReconciliation = SourceReconciliation()
    signal_stack: list[InsightSignalRow] = []
    flow_table: list[ChainFlowReadRow] = []
    term_structure_table: list[TermMoveRow] = []
    candidate_structures: list[CandidateStructure] = []
    synthesis: InsightsSynthesis = InsightsSynthesis()


# ---------------------------------------------------------------------------
# Trade Insights AI analysis (V1.5)
# ---------------------------------------------------------------------------
class TradeInsightAiBase(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=False)


class TradeInsightAiDominantRead(TradeInsightAiBase):
    headline: str
    summary: str
    confidence_commentary: str
    data_quality_commentary: str


class TradeInsightAiSnapshotMeta(TradeInsightAiBase):
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    data_as_of: str | None = None
    freshness_label: str = "unknown"
    source_notes: list[str] = Field(default_factory=list)


class TradeInsightAiHeadline(TradeInsightAiBase):
    title: str
    stance: Literal["bullish", "bearish", "neutral", "mixed", "wait"]
    stance_label: str
    score: int
    score_scale: int = 100
    conviction: str
    conviction_label: str
    top_reason: str
    primary_risk: str
    watch_trigger: str


class TradeInsightAiMetricCard(TradeInsightAiBase):
    label: str
    value: str
    tone: str = "neutral"
    source_path: str | None = None
    note: str = ""


class TradeInsightAiScenarioCard(TradeInsightAiBase):
    case: Literal["upside", "base", "downside"] | str
    tone: str = "neutral"
    title: str
    description: str


class TradeInsightAiScoreBreakdown(TradeInsightAiBase):
    section: str
    score: int
    max_score: int
    summary: str


class TradeInsightAiHighlight(TradeInsightAiBase):
    label: str
    value: str
    source_path: str | None = None
    note: str = ""


class TradeInsightAiLevel(TradeInsightAiBase):
    price: str
    kind: str
    value: str
    importance: str = "normal"
    source_path: str | None = None
    note: str = ""


class TradeInsightAiSectionCard(TradeInsightAiBase):
    title: str
    score: int | None = None
    max_score: int | None = None
    summary: str
    highlights: list[TradeInsightAiHighlight] = Field(default_factory=list)
    levels: list[TradeInsightAiLevel] = Field(default_factory=list)
    data_quality: str = "unknown"


class TradeInsightAiSectionCards(TradeInsightAiBase):
    market_structure: TradeInsightAiSectionCard
    volatility: TradeInsightAiSectionCard
    flow_positioning: TradeInsightAiSectionCard


class TradeInsightAiVrpAssessment(TradeInsightAiBase):
    signal: str
    title: str
    summary: str
    metrics: list[TradeInsightAiMetricCard] = Field(default_factory=list)
    reason: str


class TradeInsightAiPreferredExpression(TradeInsightAiBase):
    idea_id: str
    structure: str
    title: str
    subtitle: str = ""
    estimated_entry: str = ""
    max_profit_observed: str = ""
    max_loss_observed: str = ""
    reward_risk: str = ""
    why: str
    management_notes: list[str] = Field(default_factory=list)
    status_observed: str
    risk_flags_observed: list[str] = Field(default_factory=list)


class TradeInsightAiBestExpression(TradeInsightAiBase):
    idea_id: str
    structure: str
    role: str
    why: str
    caveats: list[str] = Field(default_factory=list)
    status_observed: str
    risk_flags_observed: list[str] = Field(default_factory=list)


class TradeInsightAiConflict(TradeInsightAiBase):
    lens: str
    severity: str
    description: str
    affected_idea_ids: list[str] = Field(default_factory=list)


class TradeInsightAiRequiredCheck(TradeInsightAiBase):
    check: str
    reason: str
    blocks_sizing: bool = True
    source: str = ""


class TradeInsightAiRejectedIdea(TradeInsightAiBase):
    idea_id: str
    structure: str
    reason: str


class TradeInsightAiRendering(TradeInsightAiBase):
    disclaimer: str
    card_order: list[str] = Field(default_factory=list)


class TradeInsightAiGuardrails(TradeInsightAiBase):
    statuses_preserved: bool
    risk_flags_preserved: bool
    no_executable_recommendations: bool


class TradeInsightAiOutcome(TradeInsightAiBase):
    schema_version: str
    analysis_produced_at: datetime
    ticker: str
    underlying_price: str | None = None
    snapshot: TradeInsightAiSnapshotMeta
    headline: TradeInsightAiHeadline
    metric_cards: list[TradeInsightAiMetricCard]
    scenario_cards: list[TradeInsightAiScenarioCard]
    score_breakdown: list[TradeInsightAiScoreBreakdown]
    section_cards: TradeInsightAiSectionCards
    vrp_assessment: TradeInsightAiVrpAssessment | None = None
    preferred_expression: TradeInsightAiPreferredExpression | None = None
    dominant_read: TradeInsightAiDominantRead
    best_expressions: list[TradeInsightAiBestExpression] = Field(default_factory=list)
    conflicts: list[TradeInsightAiConflict] = Field(default_factory=list)
    required_checks: list[TradeInsightAiRequiredCheck] = Field(default_factory=list)
    rejected_ideas: list[TradeInsightAiRejectedIdea] = Field(default_factory=list)
    missing_data: list[str] = Field(default_factory=list)
    rendering: TradeInsightAiRendering
    guardrails: TradeInsightAiGuardrails


class TradeInsightAiAnalysisRequest(TradeInsightAiBase):
    force_rerun: bool = False


class TradeInsightAiAnalysisResponse(TradeInsightAiBase):
    analysis_id: UUID
    ticker: str
    run_id: int
    trade_insights_input_hash: str
    analysis_input_hash: str
    model: str
    prompt_version: str
    status: Literal["queued", "running", "succeeded", "failed"]
    produced_at: datetime | None = None
    outcome: TradeInsightAiOutcome | None = None
    markdown: str | None = None
    error_message: str | None = None
    requested_at: datetime
    started_at: datetime | None = None
    finished_at: datetime | None = None
    reused: bool = False
