"""Correlation gauge — rolling Gold vs DFII10 across windows."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.regime_gauge import (
    classify_gauge_state,
    compute_correlation_gauge,
)


def _synthetic_series(
    n: int, start: date, anchor: float, slope: float
) -> list[tuple[date, Decimal]]:
    return [
        (start + timedelta(days=i), Decimal(str(anchor + slope * i))) for i in range(n)
    ]


def test_gauge_negative_correlation_when_series_anti_correlated():
    """Gold rising while TIPS yield falling → strong negative corr."""
    gold = _synthetic_series(300, date(2020, 1, 1), 1500.0, 1.5)
    tips = _synthetic_series(300, date(2020, 1, 1), 1.0, -0.005)
    g = compute_correlation_gauge(gold, tips, as_of=date(2020, 10, 25))
    assert g.corr_252d_level is not None
    assert g.corr_252d_level < Decimal("-0.95")


def test_gauge_state_thresholds():
    assert classify_gauge_state(Decimal("-0.85")) == "operative"
    assert classify_gauge_state(Decimal("-0.35")) == "partial"
    assert classify_gauge_state(Decimal("-0.05")) == "suspended"
    assert classify_gauge_state(Decimal("0.4")) == "suspended"


def test_gauge_returns_spec_is_computed_and_bounded():
    """Returns-based 252d correlation is present and within [-1, 1].

    With strictly linear synthetic price paths the log-returns are nearly
    constant so the returns correlation is numerically unstable and need
    not match the level correlation. We only assert that the value is
    computed and bounded — sign-consistency with the level spec belongs in
    an integration test with realistic price paths.
    """
    gold = _synthetic_series(300, date(2020, 1, 1), 1500.0, 1.5)
    tips = _synthetic_series(300, date(2020, 1, 1), 1.0, -0.005)
    g = compute_correlation_gauge(gold, tips, as_of=date(2020, 10, 25))
    assert g.corr_252d_returns is not None
    assert Decimal("-1.0") <= g.corr_252d_returns <= Decimal("1.0")


def test_gauge_short_series_returns_nulls():
    """Less than 60d of history → all corr values None, state suspended."""
    gold = _synthetic_series(30, date(2020, 1, 1), 1500.0, 1.0)
    tips = _synthetic_series(30, date(2020, 1, 1), 1.0, 0.0)
    g = compute_correlation_gauge(gold, tips, as_of=date(2020, 1, 30))
    assert g.corr_60d_level is None
    assert g.corr_252d_level is None
    assert g.state == "suspended"
