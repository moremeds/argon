"""DCF detector — derived ask_side_ratio, moneyness, dte from FlowAlert."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.signals.deep_conviction_flow import detect


TODAY = date(2026, 5, 17)


def _alert(
    *,
    option_type="call",
    volume=2000,
    open_interest=1000,
    total_premium="800000",
    total_ask_side_prem="700000",
    total_bid_side_prem="100000",
    has_multileg=False,
    strike="100",
    underlying_price="100",
    expiry_days=30,
    next_earnings_days: int | None = 60,
) -> FlowAlert:
    return FlowAlert(
        id="x",
        ticker="AAPL",
        type=option_type,
        strike=Decimal(strike),
        underlying_price=Decimal(underlying_price),
        total_premium=Decimal(total_premium),
        total_ask_side_prem=Decimal(total_ask_side_prem),
        total_bid_side_prem=Decimal(total_bid_side_prem),
        volume=volume,
        open_interest=open_interest,
        has_multileg=has_multileg,
        expiry=TODAY + timedelta(days=expiry_days),
        next_earnings_date=(
            TODAY + timedelta(days=next_earnings_days)
            if next_earnings_days is not None
            else None
        ),
    )


def test_qualifying_single_alert_emits_hit():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert()],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.signal_type == "deep_conviction_flow"
    assert hit.tier == 1
    assert hit.freshness == "live"
    # 0.5 + 0.5 * min(800000 / 2000000, 1.0) = 0.5 + 0.2 = 0.7
    assert hit.score == Decimal("0.7")
    assert hit.evidence["qualifying_alerts"] == 1
    assert hit.evidence["direction"] == "long"
    assert hit.evidence["top_option_type"] == "call"


def test_qualifying_put_alert_emits_short_direction():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(option_type="put")],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.evidence["direction"] == "short"
    assert hit.evidence["top_option_type"] == "put"


def test_qualifying_unknown_option_type_omits_direction():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(option_type=None)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is not None
    assert "direction" not in hit.evidence
    assert hit.evidence["top_option_type"] is None


def test_blocks_when_earnings_within_window():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(next_earnings_days=10)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_blocks_when_earnings_unknown():
    # Conservative-block — matches xenon _parse_next_earnings(None) → True.
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(next_earnings_days=None)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_when_volume_not_greater_than_oi():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(volume=1000, open_interest=1000)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_on_multileg():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(has_multileg=True)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_when_ask_side_ratio_below_threshold():
    # ask 400k / (ask 400k + bid 600k) = 0.4 — below 0.80
    hit = detect(
        ticker="AAPL",
        alerts=[
            _alert(
                total_ask_side_prem="400000",
                total_bid_side_prem="600000",
                total_premium="1000000",
            )
        ],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_on_excessive_moneyness():
    # strike 130 vs spot 100 → |moneyness| = 0.30 > 0.12
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(strike="130")],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_disqualifies_when_dte_below_floor():
    hit = detect(
        ticker="AAPL",
        alerts=[_alert(expiry_days=3)],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is None


def test_score_caps_at_one_with_huge_premium():
    hit = detect(
        ticker="AAPL",
        alerts=[
            _alert(
                total_premium="5000000",
                total_ask_side_prem="4500000",
                total_bid_side_prem="500000",
            )
        ],
        today=TODAY,
        min_premium_usd=Decimal("500000"),
        min_ask_side=Decimal("0.80"),
        max_moneyness=Decimal("0.12"),
        min_dte=6,
        earnings_window_days=14,
    )
    assert hit is not None
    assert hit.score == Decimal("1.0")
