"""Aggression % = ask_side / (ask_side + bid_side)."""

from __future__ import annotations

from decimal import Decimal

from uw_scan.cards.aggression import compute_aggression_pct
from uw_scan.models import FlowSnapshot


def _flow(ask: str, bid: str) -> FlowSnapshot:
    return FlowSnapshot(
        ticker="X",
        flow_count=0,
        net_premium=Decimal("0"),
        bull_premium=Decimal("0"),
        bear_premium=Decimal("0"),
        ask_side_premium=Decimal(ask),
        bid_side_premium=Decimal(bid),
    )


def test_aggression_pct_basic():
    assert compute_aggression_pct(_flow("80", "20")) == Decimal("0.8")


def test_aggression_pct_zero_total_returns_none():
    assert compute_aggression_pct(_flow("0", "0")) is None


def test_aggression_pct_all_ask_side_one():
    assert compute_aggression_pct(_flow("100", "0")) == Decimal("1")
