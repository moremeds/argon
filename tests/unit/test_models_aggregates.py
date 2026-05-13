"""MarketAggregates / StrikeGexBucket / SingleStockReport.aggregates round-trip through pydantic."""

from __future__ import annotations

from datetime import date as _date
from decimal import Decimal

from uw_scan.models import MarketAggregates, SingleStockReport, StrikeGexBucket


def test_market_aggregates_defaults_to_none():
    agg = MarketAggregates()
    assert agg.call_oi_total is None
    assert agg.put_oi_total is None
    assert agg.pcr_oi is None
    assert agg.pcr_vol is None


def test_market_aggregates_construct_from_screener_fields():
    agg = MarketAggregates(
        call_oi_total=1_000_000,
        put_oi_total=2_000_000,
        call_volume_total=500_000,
        put_volume_total=800_000,
        call_volume_ask_side=300_000,
        call_volume_bid_side=200_000,
        put_volume_ask_side=400_000,
        put_volume_bid_side=400_000,
        pcr_oi=Decimal("2.00"),
        pcr_vol=Decimal("1.60"),
        iv30d=Decimal("0.42"),
    )
    assert agg.pcr_oi == Decimal("2.00")
    assert agg.iv30d == Decimal("0.42")


def test_strike_gex_bucket_round_trip():
    b = StrikeGexBucket(
        strike=Decimal("450"),
        expiry=_date(2026, 6, 19),
        net_gex=Decimal("1.5"),
        call_gex=Decimal("2.0"),
        put_gex=Decimal("-0.5"),
    )
    assert b.strike == Decimal("450")
    assert b.expiry == _date(2026, 6, 19)


def test_single_stock_report_aggregates_field_optional():
    """SingleStockReport.aggregates is optional; existing fixtures keep working."""
    assert "aggregates" in SingleStockReport.model_fields
    assert SingleStockReport.model_fields["aggregates"].default is None
    assert "strike_gex_curve" in SingleStockReport.model_fields
