from datetime import date, timedelta

import pytest

from uw_scan.reports.goas_putwrite_account import curve_metrics


def _curve(values: list[float]) -> list[tuple[date, float]]:
    d0 = date(2010, 1, 4)
    return [(d0 + timedelta(days=i), v) for i, v in enumerate(values)]


def test_flat_curve_zero_vol_zero_sharpe():
    m = curve_metrics(_curve([100.0] * 50))
    assert m["ann_vol"] == pytest.approx(0.0)
    assert m["max_drawdown"] == pytest.approx(0.0)
    assert m["sharpe"] == 0.0  # guarded: zero vol → 0, not div-by-zero


def test_drawdown_is_peak_to_trough():
    # 100 → 120 → 60 → 90 : max drawdown = (60-120)/120 = -0.5
    m = curve_metrics(_curve([100.0, 120.0, 60.0, 90.0]))
    assert m["max_drawdown"] == pytest.approx(-0.5, abs=1e-9)


def test_positive_drift_with_variance_positive_sharpe():
    # positive mean daily return WITH dispersion → vol>0 and Sharpe>0. (A constant-
    # return curve has zero vol → Sharpe 0, so the test must vary the steps.)
    navs = [100.0]
    for i in range(300):
        navs.append(navs[-1] * (1 + (0.0012 if i % 2 == 0 else 0.0004)))
    m = curve_metrics(_curve(navs))
    assert m["ann_return"] > 0
    assert m["ann_vol"] > 0
    assert m["sharpe"] > 0
    assert m["max_drawdown"] == pytest.approx(0.0)
