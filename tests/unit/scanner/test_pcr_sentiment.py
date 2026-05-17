"""PCR context flag — count-based from this run's FlowAlerts."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.models import FlowAlert
from uw_scan.scanner.context.pcr_sentiment import flag


TODAY = date(2026, 5, 17)


def _alert(call_or_put: str, next_earnings_days: int | None = 60) -> FlowAlert:
    return FlowAlert(
        id="x",
        ticker="AAPL",
        type=call_or_put,
        next_earnings_date=(
            TODAY + timedelta(days=next_earnings_days)
            if next_earnings_days is not None
            else None
        ),
    )


def test_extreme_fear_when_pcr_above_1_5():
    # 6 puts / 3 calls = 2.0 > 1.5
    alerts = [_alert("put")] * 6 + [_alert("call")] * 3
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Extreme Fear"
    assert fl.value == Decimal("2.0")


def test_elevated_fear_when_pcr_between_1_2_and_1_5():
    # 7 puts / 5 calls = 1.4
    alerts = [_alert("put")] * 7 + [_alert("call")] * 5
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Elevated Fear"


def test_complacent_when_pcr_below_0_5():
    # 2 puts / 10 calls = 0.2
    alerts = [_alert("put")] * 2 + [_alert("call")] * 10
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Complacent"


def test_no_flag_when_pcr_in_neutral_band():
    # 5 puts / 5 calls = 1.0
    alerts = [_alert("put")] * 5 + [_alert("call")] * 5
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is None


def test_suppressed_when_earnings_within_window():
    alerts = [_alert("put", next_earnings_days=10)] * 6 + [
        _alert("call", next_earnings_days=10)
    ] * 3
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is None


def test_emits_when_earnings_unknown_per_spec():
    # Spec §3.5: PCR is informational, so unknown earnings does NOT suppress.
    alerts = [_alert("put", next_earnings_days=None)] * 6 + [
        _alert("call", next_earnings_days=None)
    ] * 3
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is not None
    assert fl.label == "Extreme Fear"


def test_no_calls_returns_none():
    alerts = [_alert("put")] * 5
    fl = flag(ticker="AAPL", alerts=alerts, today=TODAY, earnings_window_days=14)
    assert fl is None
