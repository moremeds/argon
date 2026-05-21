"""Subscription diff helper — pure set algebra, lifted out so the
consumer module can stay small and the WS reconnect logic doesn't need
to recompute the diff itself."""

from __future__ import annotations

from uw_scan.worker.massive_ws_consumer import compute_subscription_diff


def test_subscription_diff_initial():
    add, drop = compute_subscription_diff(
        current=set(), desired={"AAPL", "MSFT"}, channel="A"
    )
    assert add == {"A.AAPL", "A.MSFT"}
    assert drop == set()


def test_subscription_diff_add_only():
    add, drop = compute_subscription_diff(
        current={"A.AAPL"}, desired={"AAPL", "MSFT"}, channel="A"
    )
    assert add == {"A.MSFT"}
    assert drop == set()


def test_subscription_diff_drop_only():
    add, drop = compute_subscription_diff(
        current={"A.AAPL", "A.MSFT"}, desired={"AAPL"}, channel="A"
    )
    assert add == set()
    assert drop == {"A.MSFT"}


def test_subscription_diff_full_swap():
    add, drop = compute_subscription_diff(
        current={"A.AAPL", "A.MSFT"}, desired={"SPY", "QQQ"}, channel="A"
    )
    assert add == {"A.SPY", "A.QQQ"}
    assert drop == {"A.AAPL", "A.MSFT"}


def test_subscription_diff_noop_when_equal():
    add, drop = compute_subscription_diff(
        current={"A.AAPL", "A.MSFT"}, desired={"AAPL", "MSFT"}, channel="A"
    )
    assert add == set()
    assert drop == set()
