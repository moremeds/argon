"""EIC detector — needs iv_rank >= 75 AND earnings within window."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.scanner.signals.earnings_iv_crush import detect


TODAY = date(2026, 5, 17)


def test_fires_when_iv_rank_high_and_earnings_imminent():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("85"),
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.tier == 1
    assert hit.freshness == "live"
    # (85-75)/25 + 0.5 = 0.4 + 0.5 = 0.9
    assert hit.score == Decimal("0.9")


def test_no_fire_when_iv_rank_below_threshold():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("70"),
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_no_fire_when_no_earnings_in_window():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("90"),
        next_earnings_date=TODAY + timedelta(days=30),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_no_fire_when_earnings_unknown():
    # Per spec §3.3: unknown → no fire (conservative, matches DCF stance).
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("90"),
        next_earnings_date=None,
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_no_fire_when_iv_rank_missing():
    hit = detect(
        ticker="AAPL",
        iv_rank=None,
        next_earnings_date=TODAY + timedelta(days=7),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is None


def test_score_caps_at_one():
    hit = detect(
        ticker="AAPL",
        iv_rank=Decimal("100"),
        next_earnings_date=TODAY + timedelta(days=5),
        today=TODAY,
        min_iv_rank=Decimal("75"),
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.score == Decimal("1.0")
