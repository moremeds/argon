"""Charm derivers — pure functions over GreekExposureRow lists."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import (
    charm_flip,
    charm_imbalance,
    charm_narrative,
    charm_pin_strike,
    charm_signal_quality,
    net_charm,
)
from uw_scan.models import GreekExposureRow


def _r(
    strike: str, expiry: str, call_c: str | None, put_c: str | None
) -> GreekExposureRow:
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        call_charm=Decimal(call_c) if call_c is not None else None,
        put_charm=Decimal(put_c) if put_c is not None else None,
    )


def test_net_charm_sums_call_plus_put():
    rows = [
        _r("100", "2026-05-30", "-1000000", "200000"),
        _r("110", "2026-05-30", "-500000", "100000"),
    ]
    assert net_charm(rows) == Decimal("-1200000")


def test_net_charm_empty_returns_none():
    assert net_charm([]) is None


def test_charm_pin_strike_picks_max_abs():
    rows = [
        _r("100", "2026-05-30", "100", "200"),
        _r("110", "2026-05-30", "-5000", "-2000"),
        _r("120", "2026-05-30", "500", "-100"),
    ]
    assert charm_pin_strike(rows) == Decimal("110")


def test_charm_pin_strike_empty_returns_none():
    assert charm_pin_strike([]) is None


def test_charm_imbalance_splits_above_and_below_spot():
    rows = [
        _r("90", "2026-05-30", "1000", "500"),
        _r("100", "2026-05-30", "200", "100"),
        _r("110", "2026-05-30", "-3000", "-2000"),
        _r("120", "2026-05-30", "-1000", "-500"),
    ]
    above, below, imb_pct = charm_imbalance(rows, spot=Decimal("100"))
    assert above == Decimal("-6500")
    assert below == Decimal("1500")
    # imbalance % = |above - below| / (|above| + |below|) = 8000 / 8000 = 1.0
    assert imb_pct == Decimal("8000") / Decimal("8000")


def test_charm_signal_quality_aligned_when_same_sign():
    assert (
        charm_signal_quality(live=Decimal("-100000"), positioning=Decimal("-50000"))
        == "aligned"
    )


def test_charm_signal_quality_mixed_when_opposing_signs():
    assert (
        charm_signal_quality(live=Decimal("-100000"), positioning=Decimal("50000"))
        == "mixed"
    )


def test_charm_signal_quality_weak_when_either_near_zero():
    assert (
        charm_signal_quality(live=Decimal("0"), positioning=Decimal("-50000")) == "weak"
    )


def test_charm_flip_picks_cumulative_sign_change():
    rows = [
        _r("90", "2026-05-30", "1000", "500"),
        _r("100", "2026-05-30", "200", "100"),
        _r("110", "2026-05-30", "-3000", "-1500"),
        _r("120", "2026-05-30", "-100", "-50"),
    ]
    assert charm_flip(rows, spot=Decimal("100")) == Decimal("110")


def test_charm_narrative_sell_pressure_when_negative():
    headline, subtitle = charm_narrative(
        net_charm_value=Decimal("-15000000"),
        signal_quality="aligned",
    )
    assert "SELL" in headline


def test_charm_narrative_buy_pressure_when_positive():
    headline, _ = charm_narrative(
        net_charm_value=Decimal("8000000"),
        signal_quality="aligned",
    )
    assert "BUY" in headline


def test_charm_narrative_neutral_when_weak():
    headline, _ = charm_narrative(
        net_charm_value=Decimal("0"),
        signal_quality="weak",
    )
    assert "Limited" in headline or "Neutral" in headline
