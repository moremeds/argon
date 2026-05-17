"""GEX pinning — mega-caps + opex week + distance/gamma scoring."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.scanner.signals.gex_pinning import MEGA_CAPS, detect


# 3rd Friday of December 2025
OPEX_DAY = date(2025, 12, 19)
NON_OPEX_DAY = date(2025, 12, 1)


def _curve(strikes: list[tuple[float, float]]) -> list[dict]:
    """Build a strike_gex_curve payload — list of {strike, net_gex} dicts."""
    return [
        {"strike": str(strike), "net_gex": str(gamma), "expiry": "2025-12-19"}
        for strike, gamma in strikes
    ]


def test_no_fire_for_non_mega_cap():
    hit = detect(
        ticker="AMD",
        strike_gex_curve=_curve([(150.0, 5.0)]),
        spot=Decimal("150"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_no_fire_outside_opex_week():
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(500.0, 5.0)]),
        spot=Decimal("500"),
        today=NON_OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_fires_when_mega_cap_opex_and_pinning_strike_nearby():
    # SPY at $500.40, pin strike $500.00 (distance 0.08%), gamma 5.0
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(500.0, 5.0)]),
        spot=Decimal("500.40"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is not None
    assert hit.tier == 1
    # distance_pct = |500 - 500.40| / 500 * 100 = 0.08
    # distance_score = max(0, 1 - 0.08) = 0.92
    # gamma_score = min(5/10, 1.0) = 0.5
    # score = 0.5 * 0.92 + 0.5 * 0.5 = 0.71
    assert hit.score == Decimal("0.71")


def test_clamps_distance_score_at_zero_when_pin_far():
    # Distance 1.5% — distance_score would be -0.5 without the clamp.
    # detect_pinning's max_distance_pct=1.0 means the pin wouldn't be
    # returned in the first place, so the test asserts None here.
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(508.0, 5.0)]),
        spot=Decimal("500"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_no_fire_when_gamma_below_threshold():
    hit = detect(
        ticker="SPY",
        strike_gex_curve=_curve([(500.0, 0.5)]),
        spot=Decimal("500"),
        today=OPEX_DAY,
        min_gamma=Decimal("1.0"),
    )
    assert hit is None


def test_mega_caps_set_contains_required_tickers():
    for t in ("SPY", "QQQ", "IWM", "AAPL", "MSFT", "NVDA", "TSLA"):
        assert t in MEGA_CAPS
