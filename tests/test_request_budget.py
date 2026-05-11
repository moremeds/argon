from uw_scan.config import UwScanConfig
from uw_scan.request_budget import estimate_request_budget


def test_request_budget_estimates_normal_run_under_cap():
    config = UwScanConfig(max_requests_per_cycle=250)

    budget = estimate_request_budget(
        flow_rows=50,
        watchlist_symbols=15,
        deep_surface_tickers=3,
        important_expiries_per_ticker=2,
        config=config,
    )

    assert budget.total_estimated_requests <= 250
    assert budget.capped is False
    assert budget.estimated_discovery_requests == 2


def test_request_budget_caps_large_run():
    config = UwScanConfig(max_requests_per_cycle=60)

    budget = estimate_request_budget(
        flow_rows=100,
        watchlist_symbols=200,
        deep_surface_tickers=8,
        important_expiries_per_ticker=4,
        config=config,
    )

    assert budget.total_estimated_requests == 60
    assert budget.capped is True
