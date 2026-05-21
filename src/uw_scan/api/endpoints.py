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
    ETF_INFO = "etf_info"
    ETF_IN_OUTFLOW = "etf_in_outflow"
    OPTIONS_VOLUME_DAILY = "options_volume_daily"
    STOCK_STATE = "stock_state"


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
