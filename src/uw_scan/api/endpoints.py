"""Endpoint registry for UW. Each slug maps to a path template + required-param list.

The path is a template (`{ticker}` placeholder); the caller substitutes the ticker.
`required_params` is the explicit list of param names the caller must supply.
Mirrors `scripts/s0_probe_endpoint.py`'s ENDPOINTS dict in structure.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EndpointSlug(StrEnum):
    FLOW_ALERTS = "flow_alerts"
    IV_RANK = "iv_rank"
    VOLATILITY_STATS = "volatility_stats"
    REALIZED_VOLATILITY = "realized_volatility"
    TERM_STRUCTURE = "term_structure"
    INTERPOLATED_IV = "interpolated_iv"
    SKEW = "skew"
    GREEK_EXPOSURE = "greek_exposure"
    GREEK_EXPOSURE_BY_STRIKE = "greek_exposure_by_strike"
    GREEK_EXPOSURE_BY_EXPIRY = "greek_exposure_by_expiry"
    GREEK_EXPOSURE_HISTORY = "greek_exposure_history"
    SPOT_EXPOSURES = "spot_exposures"
    GREEKS = "greeks"
    OI_PER_STRIKE = "oi_per_strike"
    OI_CHANGE = "oi_change"
    MAX_PAIN = "max_pain"
    OPTION_CONTRACTS = "option_contracts"
    OPTION_CONTRACTS_BY_SYMBOL = "option_contracts_by_symbol"
    OPTION_CONTRACT_INTRADAY = "option_contract_intraday"
    DARKPOOL_TICKER = "darkpool_ticker"
    SHORT_DATA = "short_data"
    BULK_SCREENER_STOCKS = "bulk_screener_stocks"
    STOCK_INFO = "stock_info"
    ETF_INFO = "etf_info"
    ETF_IN_OUTFLOW = "etf_in_outflow"
    OPTIONS_VOLUME_DAILY = "options_volume_daily"
    STOCK_STATE = "stock_state"
    SHORT_INTEREST_FLOAT = "short_interest_float"
    ANALYST_RATINGS = "analyst_ratings"
    INSTITUTION_OWNERSHIP = "institution_ownership"
    INSIDER_TICKER_FLOW = "insider_ticker_flow"
    EARNINGS = "earnings"
    # The market-wide calendar, split by session slot. UW exposes no combined
    # endpoint, and these two carry only the names whose report_time it has
    # classified -- see sources/earnings_calendar.py for what that costs.
    EARNINGS_PREMARKET = "earnings_premarket"
    EARNINGS_AFTERHOURS = "earnings_afterhours"
    MARKET_TIDE = "market_tide"
    TOP_NET_IMPACT = "top_net_impact"
    # UW historical-alpha datasets (real but absent from the curated UW reference;
    # see docs/superpowers/specs/2026-07-24-uw-historical-alpha-capture-healing-design.md §12)
    GEX_LEVELS = "gex_levels"
    VOLATILITY_ANOMALY = "volatility_anomaly"
    VOLATILITY_CHARACTER = "volatility_character"
    VOLATILITY_VRP = "volatility_vrp"
    NET_PREM_TICKS = "net_prem_ticks"
    GREEK_FLOW = "greek_flow"
    LIT_FLOW = "lit_flow"
    FTDS = "ftds"
    VOLUMES_BY_EXCHANGE = "volumes_by_exchange"
    # Fundamental statements. `fundamental-breakdown` is the only source of real
    # filing dates; without it the pipeline must fall back to period_end + a lag,
    # which errs EARLY for late filers and manufactures look-ahead.
    INCOME_STATEMENTS = "income_statements"
    BALANCE_SHEETS = "balance_sheets"
    CASH_FLOWS = "cash_flows"
    FUNDAMENTAL_BREAKDOWN = "fundamental_breakdown"


@dataclass(frozen=True)
class Endpoint:
    slug: EndpointSlug
    path_template: str  # e.g. "/api/stock/{ticker}/iv-rank"
    required_params: tuple[str, ...] = ()


REGISTRY: dict[EndpointSlug, Endpoint] = {
    EndpointSlug.FLOW_ALERTS: Endpoint(
        EndpointSlug.FLOW_ALERTS, "/api/option-trades/flow-alerts", ()
    ),
    EndpointSlug.IV_RANK: Endpoint(
        EndpointSlug.IV_RANK, "/api/stock/{ticker}/iv-rank", ()
    ),
    EndpointSlug.VOLATILITY_STATS: Endpoint(
        EndpointSlug.VOLATILITY_STATS, "/api/stock/{ticker}/volatility/stats", ()
    ),
    EndpointSlug.REALIZED_VOLATILITY: Endpoint(
        EndpointSlug.REALIZED_VOLATILITY, "/api/stock/{ticker}/volatility/realized", ()
    ),
    EndpointSlug.TERM_STRUCTURE: Endpoint(
        EndpointSlug.TERM_STRUCTURE, "/api/stock/{ticker}/volatility/term-structure", ()
    ),
    EndpointSlug.INTERPOLATED_IV: Endpoint(
        EndpointSlug.INTERPOLATED_IV, "/api/stock/{ticker}/interpolated-iv", ()
    ),
    EndpointSlug.SKEW: Endpoint(
        EndpointSlug.SKEW,
        "/api/stock/{ticker}/historical-risk-reversal-skew",
        ("expiry", "delta"),
    ),
    EndpointSlug.GREEK_EXPOSURE: Endpoint(
        EndpointSlug.GREEK_EXPOSURE,
        "/api/stock/{ticker}/greek-exposure/strike-expiry",
        ("expiry",),
    ),
    EndpointSlug.GREEK_EXPOSURE_BY_STRIKE: Endpoint(
        EndpointSlug.GREEK_EXPOSURE_BY_STRIKE,
        "/api/stock/{ticker}/greek-exposure/strike",
        (),
    ),
    EndpointSlug.GREEK_EXPOSURE_BY_EXPIRY: Endpoint(
        EndpointSlug.GREEK_EXPOSURE_BY_EXPIRY,
        "/api/stock/{ticker}/greek-exposure/expiry",
        (),
    ),
    EndpointSlug.GREEK_EXPOSURE_HISTORY: Endpoint(
        EndpointSlug.GREEK_EXPOSURE_HISTORY,
        "/api/stock/{ticker}/greek-exposure",
        (),
    ),
    EndpointSlug.SPOT_EXPOSURES: Endpoint(
        EndpointSlug.SPOT_EXPOSURES,
        "/api/stock/{ticker}/spot-exposures/expiry-strike",
        ("expirations[]",),
    ),
    EndpointSlug.GREEKS: Endpoint(
        EndpointSlug.GREEKS, "/api/stock/{ticker}/greeks", ("expiry",)
    ),
    EndpointSlug.OI_PER_STRIKE: Endpoint(
        EndpointSlug.OI_PER_STRIKE, "/api/stock/{ticker}/oi-per-strike", ()
    ),
    EndpointSlug.OI_CHANGE: Endpoint(
        EndpointSlug.OI_CHANGE, "/api/stock/{ticker}/oi-change", ()
    ),
    EndpointSlug.MAX_PAIN: Endpoint(
        EndpointSlug.MAX_PAIN, "/api/stock/{ticker}/max-pain", ()
    ),
    EndpointSlug.OPTION_CONTRACTS: Endpoint(
        EndpointSlug.OPTION_CONTRACTS, "/api/stock/{ticker}/option-contracts", ()
    ),
    EndpointSlug.OPTION_CONTRACTS_BY_SYMBOL: Endpoint(
        EndpointSlug.OPTION_CONTRACTS_BY_SYMBOL,
        "/api/stock/{ticker}/option-contracts",
        ("option_symbol[]",),
    ),
    EndpointSlug.OPTION_CONTRACT_INTRADAY: Endpoint(
        EndpointSlug.OPTION_CONTRACT_INTRADAY,
        "/api/option-contract/{option_symbol}/intraday",
        ("date",),
    ),
    EndpointSlug.DARKPOOL_TICKER: Endpoint(
        EndpointSlug.DARKPOOL_TICKER, "/api/darkpool/{ticker}", ()
    ),
    EndpointSlug.SHORT_DATA: Endpoint(
        EndpointSlug.SHORT_DATA, "/api/shorts/{ticker}/data", ()
    ),
    EndpointSlug.BULK_SCREENER_STOCKS: Endpoint(
        EndpointSlug.BULK_SCREENER_STOCKS, "/api/screener/stocks", ()
    ),
    EndpointSlug.STOCK_INFO: Endpoint(
        EndpointSlug.STOCK_INFO, "/api/stock/{ticker}/info", ()
    ),
    EndpointSlug.ETF_INFO: Endpoint(
        EndpointSlug.ETF_INFO, "/api/etfs/{ticker}/info", ()
    ),
    EndpointSlug.ETF_IN_OUTFLOW: Endpoint(
        EndpointSlug.ETF_IN_OUTFLOW, "/api/etfs/{ticker}/in-outflow", ()
    ),
    EndpointSlug.OPTIONS_VOLUME_DAILY: Endpoint(
        EndpointSlug.OPTIONS_VOLUME_DAILY,
        "/api/stock/{ticker}/options-volume",
        (),
    ),
    EndpointSlug.STOCK_STATE: Endpoint(
        EndpointSlug.STOCK_STATE,
        "/api/stock/{ticker}/stock-state",
        (),
    ),
    EndpointSlug.SHORT_INTEREST_FLOAT: Endpoint(
        EndpointSlug.SHORT_INTEREST_FLOAT,
        "/api/shorts/{ticker}/interest-float/v2",
        (),
    ),
    EndpointSlug.ANALYST_RATINGS: Endpoint(
        EndpointSlug.ANALYST_RATINGS,
        "/api/screener/analysts",
        (),
    ),
    EndpointSlug.INSTITUTION_OWNERSHIP: Endpoint(
        EndpointSlug.INSTITUTION_OWNERSHIP,
        "/api/institution/{ticker}/ownership",
        (),
    ),
    EndpointSlug.INSIDER_TICKER_FLOW: Endpoint(
        EndpointSlug.INSIDER_TICKER_FLOW,
        "/api/insider/{ticker}/ticker-flow",
        (),
    ),
    EndpointSlug.EARNINGS: Endpoint(
        EndpointSlug.EARNINGS,
        "/api/earnings/{ticker}",
        (),
    ),
    EndpointSlug.EARNINGS_PREMARKET: Endpoint(
        EndpointSlug.EARNINGS_PREMARKET,
        "/api/earnings/premarket",
        (),
    ),
    EndpointSlug.EARNINGS_AFTERHOURS: Endpoint(
        EndpointSlug.EARNINGS_AFTERHOURS,
        "/api/earnings/afterhours",
        (),
    ),
    EndpointSlug.MARKET_TIDE: Endpoint(
        EndpointSlug.MARKET_TIDE,
        "/api/market/market-tide",
        (),
    ),
    EndpointSlug.TOP_NET_IMPACT: Endpoint(
        EndpointSlug.TOP_NET_IMPACT,
        "/api/market/top-net-impact",
        (),
    ),
    # UW historical-alpha datasets. `date`/`limit` are optional selectors -> ().
    # LIT_FLOW is top-level (/api/lit-flow/{ticker}), NOT under /api/stock/.
    EndpointSlug.GEX_LEVELS: Endpoint(
        EndpointSlug.GEX_LEVELS, "/api/stock/{ticker}/gex-levels", ()
    ),
    EndpointSlug.VOLATILITY_ANOMALY: Endpoint(
        EndpointSlug.VOLATILITY_ANOMALY, "/api/stock/{ticker}/volatility/anomaly", ()
    ),
    EndpointSlug.VOLATILITY_CHARACTER: Endpoint(
        EndpointSlug.VOLATILITY_CHARACTER,
        "/api/stock/{ticker}/volatility/character",
        (),
    ),
    EndpointSlug.VOLATILITY_VRP: Endpoint(
        EndpointSlug.VOLATILITY_VRP,
        "/api/stock/{ticker}/volatility/variance-risk-premium",
        (),
    ),
    EndpointSlug.NET_PREM_TICKS: Endpoint(
        EndpointSlug.NET_PREM_TICKS, "/api/stock/{ticker}/net-prem-ticks", ()
    ),
    EndpointSlug.GREEK_FLOW: Endpoint(
        EndpointSlug.GREEK_FLOW, "/api/stock/{ticker}/greek-flow", ()
    ),
    EndpointSlug.LIT_FLOW: Endpoint(
        EndpointSlug.LIT_FLOW, "/api/lit-flow/{ticker}", ()
    ),
    EndpointSlug.FTDS: Endpoint(EndpointSlug.FTDS, "/api/shorts/{ticker}/ftds", ()),
    EndpointSlug.VOLUMES_BY_EXCHANGE: Endpoint(
        EndpointSlug.VOLUMES_BY_EXCHANGE,
        "/api/shorts/{ticker}/volumes-by-exchange",
        (),
    ),
    EndpointSlug.INCOME_STATEMENTS: Endpoint(
        EndpointSlug.INCOME_STATEMENTS, "/api/stock/{ticker}/income-statements", ()
    ),
    EndpointSlug.BALANCE_SHEETS: Endpoint(
        EndpointSlug.BALANCE_SHEETS, "/api/stock/{ticker}/balance-sheets", ()
    ),
    EndpointSlug.CASH_FLOWS: Endpoint(
        EndpointSlug.CASH_FLOWS, "/api/stock/{ticker}/cash-flows", ()
    ),
    EndpointSlug.FUNDAMENTAL_BREAKDOWN: Endpoint(
        EndpointSlug.FUNDAMENTAL_BREAKDOWN,
        "/api/stock/{ticker}/fundamental-breakdown",
        (),
    ),
}


def build_path(
    slug: EndpointSlug,
    ticker: str | None = None,
    *,
    option_symbol: str | None = None,
) -> str:
    """Render an endpoint path with optional ticker or option_symbol substitution."""
    template = REGISTRY[slug].path_template
    if "{ticker}" in template:
        if not ticker:
            raise ValueError(f"endpoint {slug} requires a ticker")
        return template.replace("{ticker}", ticker.upper())
    if "{option_symbol}" in template:
        if not option_symbol:
            raise ValueError(f"endpoint {slug} requires an option_symbol")
        return template.replace("{option_symbol}", option_symbol.upper())
    return template
