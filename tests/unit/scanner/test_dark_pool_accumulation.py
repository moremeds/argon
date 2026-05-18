"""DP cluster detector — anchor-price clustering with USD thresholds."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

from uw_scan.scanner.signals.dark_pool_accumulation import detect

NOW = datetime(2026, 5, 17, 16, 0, tzinfo=timezone.utc)


def _print(price, premium, hours_ago=1):
    return {
        "tracking_id": int(price * 1000),
        "executed_at": NOW - timedelta(hours=hours_ago),
        "price": Decimal(str(price)),
        "size": 1000,
        "premium": Decimal(str(premium)),
    }


def test_three_prints_in_band_above_threshold_fires():
    prints = [
        _print(185.00, 1_200_000),
        _print(185.50, 1_300_000),  # within 0.5% band
        _print(184.80, 1_500_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is not None
    assert hit.tier == 2
    assert hit.freshness == "stale"
    assert hit.evidence["cluster_size"] >= 3
    assert hit.evidence["direction_neutral"] is True


def test_returns_none_when_no_print_above_threshold():
    prints = [
        _print(185.00, 500_000),
        _print(185.10, 700_000),
        _print(185.20, 800_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is None


def test_returns_none_when_prints_too_spread():
    prints = [
        _print(180.00, 1_100_000),
        _print(190.00, 1_100_000),  # ~5.5% away — outside 0.5% band
        _print(200.00, 1_100_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is None


def test_score_grows_with_total_premium_capped_at_one():
    prints = [_print(100 + i * 0.1, 5_000_000, hours_ago=i) for i in range(3)]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
    )
    assert hit is not None
    assert hit.score == Decimal("1.0")


def test_vs_spot_below_when_cluster_vwap_under_spot():
    prints = [
        _print(184.50, 1_200_000),
        _print(184.60, 1_300_000),
        _print(184.55, 1_500_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
        spot=Decimal("190.00"),
    )
    assert hit is not None
    assert hit.evidence["vs_spot"] == "below"
    # vwap ≈ (184.50*1.2 + 184.60*1.3 + 184.55*1.5) / 4.0 = 184.55
    # (184.55 - 190.00) / 190.00 * 100 ≈ -2.87%
    assert hit.evidence["vs_spot_pct"] == "-2.87"
    assert hit.evidence["spot"] == "190.00"
    assert hit.evidence["cluster_price_min"] == "184.50"
    assert hit.evidence["cluster_price_max"] == "184.60"
    assert hit.evidence["cluster_price_vwap"] == "184.55"


def test_vs_spot_above_when_cluster_anchor_over_spot():
    prints = [
        _print(195.00, 1_200_000),
        _print(195.10, 1_300_000),
        _print(195.05, 1_500_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
        spot=Decimal("190.00"),
    )
    assert hit is not None
    assert hit.evidence["vs_spot"] == "above"


def test_vs_spot_at_when_cluster_within_tolerance_band():
    prints = [
        _print(190.05, 1_200_000),
        _print(190.02, 1_300_000),
        _print(190.04, 1_500_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
        spot=Decimal("190.00"),
    )
    assert hit is not None
    # 190.05 is +0.026% — within ±0.05% tolerance.
    assert hit.evidence["vs_spot"] == "at"


def test_vs_spot_unknown_when_spot_missing():
    prints = [
        _print(185.00, 1_200_000),
        _print(185.10, 1_300_000),
        _print(184.95, 1_500_000),
    ]
    hit = detect(
        ticker="AAPL",
        dark_pool_prints=prints,
        min_print_premium=Decimal("1000000"),
        min_cluster_size=3,
        price_spread_pct=Decimal("0.5"),
        spot=None,
    )
    assert hit is not None
    assert hit.evidence["vs_spot"] == "unknown"
    assert hit.evidence["vs_spot_pct"] is None
