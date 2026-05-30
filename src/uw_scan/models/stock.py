"""Single-stock aggregate contracts."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime
from decimal import Decimal

from ._base import _preserve_public_module, _UwBase
from .flow import FlowSnapshot, ShortDataRow
from .matrix import SetupClassification
from .options import (
    MaxPainRow,
    OiChangeRow,
    OptionChainPerStrikeRow,
    OptionIntradayProfile,
    OptionsDailyRow,
)
from .scanner import (
    DealerRegime,
    ExposuresSummaryRow,
    MarketAggregates,
    MarketStructureLevels,
    StrikeExposureRow,
    StrikeGexBucket,
)


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


class VRPAssessment(_UwBase):
    vrp: Decimal | None = None
    signal: str
    note: str


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
    dark_pool_notional: Decimal | None = None
    dark_pool_print_count: int = 0
    short_data: ShortDataRow | None = None
    max_pain_rows: list[MaxPainRow] = []
    oi_change_top: list[OiChangeRow] = []
    # Per-contract intraday TAPE view (peak window, first/last trade,
    # sparkline) for the top OI movers — derived from persisted UW
    # per-minute intraday bars by ``cards.intraday_profile``. Empty when
    # the intraday refresh job hasn't filled the cache yet.
    oi_change_intraday_profiles: list[OptionIntradayProfile] = []
    aggregates: MarketAggregates | None = None
    strike_gex_curve: list[StrikeGexBucket] = []
    market_structure_levels: MarketStructureLevels | None = None
    options_timeline: list[OptionsDailyRow] = []
    option_chain_per_strike: list[OptionChainPerStrikeRow] = []
    strike_exposures: list[StrikeExposureRow] = []
    exposures_summary: list[ExposuresSummaryRow] = []
    # Promoted from FlowAlert.next_earnings_date so the Volume-timeline panel
    # can render the earnings marker without iterating alerts on the client.
    next_earnings_date: _date | None = None
    # Per-ticker dealer Greek regime — feeds the Magnet/Gamma summary bar
    # above the GEX profile. Optional so reports without exposures_summary
    # data still serialize.
    dealer_regime: DealerRegime | None = None


_preserve_public_module(
    MarketStructure,
    VolatilityProfile,
    VRPAssessment,
    StockHistoryRow,
    StockHistoryResponse,
    SingleStockReport,
)
