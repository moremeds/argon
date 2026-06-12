"""Regime symbols merge into the WS subscription diff."""

from __future__ import annotations

from uw_scan.worker.massive_ws_consumer import (
    compute_subscription_diff,
    desired_subscription_tickers,
)


def test_desired_merges_watchlist_and_regime_set():
    out = desired_subscription_tickers({"AAPL", "spy"}, ["VIX", "hyg"])
    assert out == {"AAPL", "SPY", "VIX", "HYG"}


def test_diff_subscribes_regime_symbols():
    desired = desired_subscription_tickers({"AAPL"}, ["VIX", "VVIX"])
    to_add, to_drop = compute_subscription_diff(
        current={"A.AAPL"}, desired=desired, channel="A"
    )
    assert to_add == {"A.VIX", "A.VVIX"}
    assert to_drop == set()
