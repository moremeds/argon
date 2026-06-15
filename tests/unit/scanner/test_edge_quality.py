"""Unit tests for the edge-quality scorer (radon parity, premium-free)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.scanner import edge_quality as eq


def _dp_row(d, price, bid, ask, size=1000):
    return {
        "executed_at": d,
        "price": Decimal(str(price)),
        "nbbo_bid": Decimal(str(bid)),
        "nbbo_ask": Decimal(str(ask)),
        "size": size,
    }


def test_analyze_darkpool_day_accumulation():
    # All prints above mid → buy-heavy → ACCUMULATION.
    trades = [_dp_row(None, 10.0, 9.0, 9.5) for _ in range(5)]
    out = eq.analyze_darkpool_day(trades)
    assert out["direction"] == "ACCUMULATION"
    assert out["strength"] == Decimal("100.0")  # ratio 1.0 → (1.0-0.5)*200=100


def test_analyze_darkpool_day_distribution():
    trades = [_dp_row(None, 8.5, 9.0, 10.0) for _ in range(5)]  # below mid (9.5)
    out = eq.analyze_darkpool_day(trades)
    assert out["direction"] == "DISTRIBUTION"


def test_analyze_darkpool_day_no_data():
    assert eq.analyze_darkpool_day([])["direction"] == "NO_DATA"


def test_directional_darkpool_sustained_counts_consecutive_days():
    d1 = datetime(2026, 6, 15, 14, tzinfo=timezone.utc)
    d2 = datetime(2026, 6, 12, 14, tzinfo=timezone.utc)
    d3 = datetime(2026, 6, 11, 14, tzinfo=timezone.utc)
    window = (
        [_dp_row(d1, 10.0, 9.0, 9.5)]  # ACC
        + [_dp_row(d2, 10.0, 9.0, 9.5)]  # ACC
        + [_dp_row(d3, 8.0, 9.0, 10.0)]  # DIST → breaks the streak
    )
    out = eq.directional_darkpool(window)
    assert out["sustained_days"] == 2
    assert out["aggregate"]["direction"] == "ACCUMULATION"


def test_directional_darkpool_dedups_repeated_tracking_ids():
    d1 = datetime(2026, 6, 15, 14, tzinfo=timezone.utc)
    row = {**_dp_row(d1, 10.0, 9.0, 9.5, size=1000), "tracking_id": 42}
    out = eq.directional_darkpool([row, dict(row), dict(row)])  # same tid x3
    assert out["aggregate"]["prints"] == 1  # counted once, not 3
    assert out["total_prints"] == 1


def test_calculate_score_excludes_premium():
    out = eq.calculate_score(
        dp_strength=Decimal("60"),
        dp_sustained=2,  # → 40 capped→ min(40,100)=40
        has_confluence=True,  # → 100
        vol_oi_ratio=Decimal("2.0"),  # → 50
        sweep_count=2,  # → 100
    )
    # weighted: 60*.30 + 40*.20 + 100*.20 + 50*.15 + 100*.15
    #         = 18 + 8 + 20 + 7.5 + 15 = 68.5
    assert out["total"] == Decimal("68.5")
    assert "premium" not in out["weighted"]
    assert "premium" not in out["components"]


def test_options_bias_and_confluence():
    assert eq.options_bias(calls=4, puts=1) == "bullish"
    assert eq.options_bias(calls=1, puts=4) == "bearish"
    assert eq.options_bias(calls=2, puts=2) == "mixed"
    assert eq.has_confluence("bullish", "ACCUMULATION") is True
    assert eq.has_confluence("bearish", "DISTRIBUTION") is True
    assert eq.has_confluence("bullish", "DISTRIBUTION") is False
