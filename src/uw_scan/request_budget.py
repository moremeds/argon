from __future__ import annotations

from .config import UwScanConfig
from .models import RequestBudgetSummary


def estimate_request_budget(
    *,
    flow_rows: int,
    watchlist_symbols: int,
    deep_surface_tickers: int,
    important_expiries_per_ticker: int,
    config: UwScanConfig,
) -> RequestBudgetSummary:
    capped_flow_rows = min(flow_rows, config.max_flow_rows)
    capped_watchlist_symbols = min(watchlist_symbols, config.max_watchlist_tickers)
    capped_deep_tickers = min(deep_surface_tickers, config.max_deep_surface_tickers)
    capped_expiries = min(important_expiries_per_ticker, config.max_expiries_per_ticker)

    discovery = 2
    enrichment = capped_watchlist_symbols * 12
    exact_contract_refresh = max(1, capped_flow_rows // 25)
    deep_surface = capped_deep_tickers * (1 + capped_expiries * 2)

    raw_total = discovery + enrichment + exact_contract_refresh + deep_surface
    total = min(raw_total, config.max_requests_per_cycle)

    return RequestBudgetSummary(
        flow_rows=capped_flow_rows,
        watchlist_symbols=capped_watchlist_symbols,
        estimated_discovery_requests=discovery,
        estimated_enrichment_requests=enrichment + exact_contract_refresh,
        estimated_deep_surface_requests=deep_surface,
        total_estimated_requests=total,
        max_requests_per_cycle=config.max_requests_per_cycle,
        capped=raw_total > config.max_requests_per_cycle,
    )
