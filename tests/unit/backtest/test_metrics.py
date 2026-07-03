from __future__ import annotations

import math

from uw_scan.backtest.metrics import (
    additive_max_drawdown,
    annualized_sharpe,
    hit_rate,
    monthly_summary,
    zero_filled_monthly,
)


def test_sharpe_hand_derived():
    # mean 0.02, pstdev 0.01 -> 2 * sqrt(12)
    assert (
        abs(annualized_sharpe([0.03, 0.01], periods_per_year=12) - 2 * math.sqrt(12))
        < 1e-12
    )


def test_sharpe_zero_mean_is_zero():
    assert annualized_sharpe([0.01, -0.01], periods_per_year=12) == 0.0


def test_sharpe_degenerate_inputs_are_nan():
    assert math.isnan(annualized_sharpe([], periods_per_year=12))
    assert math.isnan(
        annualized_sharpe([0.02, 0.02], periods_per_year=12)
    )  # zero dispersion


def test_additive_max_drawdown():
    # cum: .05, .03, .00, .04 ; peak .05 -> worst -.05
    assert additive_max_drawdown([0.05, -0.02, -0.03, 0.04]) == -0.05
    assert additive_max_drawdown([]) == 0.0
    assert additive_max_drawdown([0.01, 0.02]) == 0.0  # monotone up


def test_hit_rate():
    assert hit_rate([0.01, -0.02, 0.03]) == 2 / 3
    assert math.isnan(hit_rate([]))


def test_zero_filled_monthly_spans_year_boundary():
    monthly = {(2025, 11): 0.01, (2026, 2): 0.04}
    assert zero_filled_monthly(monthly) == [0.01, 0.0, 0.0, 0.04]
    assert zero_filled_monthly({}) == []


def test_monthly_summary_matches_legacy_sharpe_maxdd_semantics():
    # exact port of scripts/_vrp_macro_param_sweep.py::_sharpe_maxdd
    monthly = {(2026, 1): 0.03, (2026, 3): 0.01}  # gap month zero-filled
    s = monthly_summary(monthly)
    series = [0.03, 0.0, 0.01]
    mean = sum(series) / 3
    var = sum((x - mean) ** 2 for x in series) / 3  # population
    assert abs(s["sharpe"] - mean / math.sqrt(var) * math.sqrt(12)) < 1e-12
    assert s["maxdd"] == 0.0  # cum .03,.03,.04 is monotone non-decreasing — no drawdown
    assert abs(s["annror"] - mean * 12) < 1e-12


def test_monthly_summary_empty():
    s = monthly_summary({})
    assert math.isnan(s["sharpe"]) and s["maxdd"] == 0.0 and s["annror"] == 0.0
