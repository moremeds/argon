"""Vanna derivers — pure functions over GreekExposureRow lists."""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from uw_scan.cards.exposures import (
    delta_shock_1pt_iv,
    net_vanna,
    top_vanna_strike,
    vanna_flip,
    vanna_narrative,
    vanna_regime,
)
from uw_scan.models import GreekExposureRow


def _r(
    strike: str, expiry: str, call_v: str | None, put_v: str | None
) -> GreekExposureRow:
    return GreekExposureRow(
        date=date.fromisoformat("2026-05-21"),
        expiry=date.fromisoformat(expiry),
        strike=Decimal(strike),
        call_vanna=Decimal(call_v) if call_v is not None else None,
        put_vanna=Decimal(put_v) if put_v is not None else None,
    )


def test_net_vanna_sums_call_plus_put_across_rows():
    rows = [
        _r("100", "2026-05-30", "100", "-30"),
        _r("110", "2026-05-30", "200", "-40"),
    ]
    assert net_vanna(rows) == Decimal("230")


def test_net_vanna_handles_nulls_silently():
    rows = [
        _r("100", "2026-05-30", "100", None),
        _r("110", "2026-05-30", None, "-40"),
    ]
    assert net_vanna(rows) == Decimal("60")


def test_net_vanna_empty_returns_none():
    assert net_vanna([]) is None


def test_top_vanna_strike_picks_max_absolute_per_strike():
    rows = [
        _r("100", "2026-05-30", "50", "-10"),
        _r("110", "2026-05-30", "-200", "30"),
        _r("120", "2026-05-30", "80", "20"),
    ]
    strike, value = top_vanna_strike(rows)
    assert strike == Decimal("110")
    assert value == Decimal("-170")


def test_top_vanna_strike_empty_returns_none():
    assert top_vanna_strike([]) is None


def test_delta_shock_1pt_iv_is_net_vanna_times_001():
    """UW vanna is dDelta per unit of vol (decimal); 1pt IV = 0.01."""
    rows = [_r("100", "2026-05-30", "10000", "-2000")]
    assert delta_shock_1pt_iv(rows) == Decimal("80.00")


def test_vanna_regime_procyclical_when_net_positive():
    assert vanna_regime(Decimal("1500000")) == "procyclical"


def test_vanna_regime_countercyclical_when_net_negative():
    assert vanna_regime(Decimal("-1500000")) == "countercyclical"


def test_vanna_regime_neutral_below_threshold():
    assert vanna_regime(Decimal("500")) == "neutral"
    assert vanna_regime(None) == "neutral"


def test_vanna_flip_picks_first_cumulative_sign_change():
    rows = [
        _r("90", "2026-05-30", "-100", "0"),
        _r("100", "2026-05-30", "-50", "0"),
        _r("110", "2026-05-30", "200", "0"),
        _r("120", "2026-05-30", "50", "0"),
    ]
    assert vanna_flip(rows, spot=Decimal("100")) == Decimal("110")


def test_vanna_flip_no_sign_change_returns_none():
    rows = [
        _r("90", "2026-05-30", "10", "0"),
        _r("100", "2026-05-30", "20", "0"),
    ]
    assert vanna_flip(rows, spot=Decimal("95")) is None


def test_vanna_flip_picks_lowest_ge_spot_when_multiple():
    """Spec rule: lowest sign-flip >= spot; fall back to lowest overall otherwise."""
    rows = [
        _r("80", "2026-05-30", "-100", "0"),
        _r("90", "2026-05-30", "200", "0"),
        _r("100", "2026-05-30", "-300", "0"),
        _r("110", "2026-05-30", "400", "0"),
    ]
    assert vanna_flip(rows, spot=Decimal("100")) == Decimal("100")


def test_vanna_flip_falls_back_to_lowest_when_no_flip_above_spot():
    rows = [
        _r("80", "2026-05-30", "-100", "0"),
        _r("90", "2026-05-30", "200", "0"),
    ]
    assert vanna_flip(rows, spot=Decimal("150")) == Decimal("90")


def test_vanna_narrative_procyclical():
    headline, subtitle = vanna_narrative(Decimal("1300000"), "procyclical")
    assert "Long Vanna" in headline
    assert "IV" in subtitle


def test_vanna_narrative_countercyclical():
    headline, subtitle = vanna_narrative(Decimal("-800000"), "countercyclical")
    assert "Short Vanna" in headline
