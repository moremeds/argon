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
    SPOT_EXPOSURES = "spot_exposures"
    GREEKS = "greeks"
    OI_PER_STRIKE = "oi_per_strike"
    OI_CHANGE = "oi_change"
    MAX_PAIN = "max_pain"
    OPTION_CONTRACTS = "option_contracts"
    OPTION_CONTRACTS_BY_SYMBOL = "option_contracts_by_symbol"
    DARKPOOL_TICKER = "darkpool_ticker"
    SHORT_DATA = "short_data"
    BULK_SCREENER_STOCKS = "bulk_screener_stocks"
    OPTIONS_VOLUME_DAILY = "options_volume_daily"


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
    EndpointSlug.DARKPOOL_TICKER: Endpoint(
        EndpointSlug.DARKPOOL_TICKER, "/api/darkpool/{ticker}", ()
    ),
    EndpointSlug.SHORT_DATA: Endpoint(
        EndpointSlug.SHORT_DATA, "/api/shorts/{ticker}/data", ()
    ),
    EndpointSlug.BULK_SCREENER_STOCKS: Endpoint(
        EndpointSlug.BULK_SCREENER_STOCKS, "/api/screener/stocks", ()
    ),
    EndpointSlug.OPTIONS_VOLUME_DAILY: Endpoint(
        EndpointSlug.OPTIONS_VOLUME_DAILY,
        "/api/stock/{ticker}/options-volume",
        (),
    ),
}


def build_path(slug: EndpointSlug, ticker: str | None = None) -> str:
    """Render an endpoint path with optional ticker substitution."""
    template = REGISTRY[slug].path_template
    if "{ticker}" in template:
        if not ticker:
            raise ValueError(f"endpoint {slug} requires a ticker")
        return template.replace("{ticker}", ticker.upper())
    return template
