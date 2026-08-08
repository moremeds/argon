import math

import pytest

from uw_scan.reports.magnet_data import (
    atm_iv_at_horizon,
    interp_atm_iv,
    normalize_iv,
)


def test_normalize_iv_passes_decimal_through():
    assert normalize_iv(0.42) == pytest.approx(0.42)


def test_normalize_iv_converts_percent():
    # The grid stores some sessions as percent. load_atm_iv uses the same >3.0 rule.
    assert normalize_iv(42.0) == pytest.approx(0.42)


def test_interp_atm_iv_is_linear_in_total_variance():
    # w = sigma^2 * dte.  near: 0.40^2*7 = 1.12   far: 0.30^2*28 = 2.52
    # target 14 sits 1/3 of the way from 7 to 28 -> w = 1.12 + (2.52-1.12)/3
    got = interp_atm_iv(0.40, 7, 0.30, 28, 14)
    assert got == pytest.approx(
        math.sqrt((1.12 + (2.52 - 1.12) / 3.0) / 14.0), rel=1e-9
    )


def test_interp_atm_iv_returns_endpoint_when_target_equals_near():
    assert interp_atm_iv(0.40, 7, 0.30, 28, 7) == pytest.approx(0.40)


def test_interp_atm_iv_rejects_non_positive_target():
    with pytest.raises(ValueError):
        interp_atm_iv(0.40, 7, 0.30, 28, 0)


def test_atm_iv_at_horizon_interpolates_between_straddling_expiries():
    curve = [(7, 0.40), (28, 0.30)]
    assert atm_iv_at_horizon(curve, 14) == pytest.approx(
        interp_atm_iv(0.40, 7, 0.30, 28, 14)
    )


def test_atm_iv_at_horizon_uses_exact_expiry_when_present():
    assert atm_iv_at_horizon([(7, 0.40), (14, 0.35), (28, 0.30)], 14) == pytest.approx(
        0.35
    )


def test_atm_iv_at_horizon_rejects_an_expiry_more_than_twice_the_target():
    # A 90-day expiry is not a measurement of a 7-day cone.
    assert atm_iv_at_horizon([(90, 0.30)], 7) is None


def test_atm_iv_at_horizon_rejects_an_expiry_less_than_half_the_target():
    assert atm_iv_at_horizon([(3, 0.60)], 14) is None


def test_atm_iv_at_horizon_accepts_a_single_nearby_expiry():
    assert atm_iv_at_horizon([(10, 0.33)], 7) == pytest.approx(0.33)


def test_atm_iv_at_horizon_returns_none_on_an_empty_curve():
    assert atm_iv_at_horizon([], 7) is None
