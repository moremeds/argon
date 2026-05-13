"""GEX derivations: flip strike, max strike, expiring %."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.gex import find_flip_strike, gex_expiring_pct, max_gex_strike
from uw_scan.models import StrikeGexBucket


def _b(strike: str, expiry: str, net: str) -> StrikeGexBucket:
    return StrikeGexBucket(
        strike=Decimal(strike),
        expiry=date.fromisoformat(expiry),
        net_gex=Decimal(net),
    )


def test_find_flip_strike_simple_sign_change():
    curve = [
        _b("90", "2026-05-30", "-30"),
        _b("100", "2026-05-30", "-10"),
        _b("110", "2026-05-30", "20"),
        _b("120", "2026-05-30", "40"),
    ]
    assert find_flip_strike(curve) == Decimal("110")


def test_find_flip_strike_all_positive_returns_none():
    curve = [_b("100", "2026-05-30", "10"), _b("110", "2026-05-30", "20")]
    assert find_flip_strike(curve) is None


def test_find_flip_strike_empty_curve_returns_none():
    assert find_flip_strike([]) is None


def test_max_gex_strike_picks_largest_absolute():
    curve = [
        _b("100", "2026-05-30", "10"),
        _b("110", "2026-05-30", "-50"),
        _b("120", "2026-05-30", "25"),
    ]
    assert max_gex_strike(curve) == Decimal("110")


def test_gex_expiring_pct_bucketed_by_expiry():
    curve = [
        _b("100", "2026-05-30", "10"),
        _b("110", "2026-05-30", "-30"),
        _b("100", "2026-06-20", "50"),
        _b("110", "2026-06-20", "-5"),
    ]
    pct = gex_expiring_pct(curve)
    assert pct is not None
    expected = Decimal("20") / Decimal("65")
    assert abs(pct - expected) < Decimal("0.0001")


def test_gex_expiring_pct_empty_curve_returns_none():
    assert gex_expiring_pct([]) is None


def test_gex_expiring_pct_all_zero_returns_none():
    curve = [_b("100", "2026-05-30", "0"), _b("110", "2026-05-30", "0")]
    assert gex_expiring_pct(curve) is None
