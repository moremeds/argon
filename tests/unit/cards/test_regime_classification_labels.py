from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from uw_scan.cards.regime_classification_labels import (
    apply_bounce_state_machine,
    classify_level1_instantaneous,
    compute_realized_vol,
    compute_rolling_percentile_rank,
    compute_trailing_drawdown,
    derive_level1_frame,
)

# ---- Task 3.1: realized vol + drawdown ----


def test_realized_vol_constant_returns_is_zero():
    """Constant +1% daily growth: log returns are constant -> realized vol = 0."""
    close = pd.Series([100.0 * (1.01**i) for i in range(30)])
    rv = compute_realized_vol(close, window=21)
    assert rv.iloc[-1] == pytest.approx(0.0, abs=1e-9)


def test_realized_vol_alternating_returns_matches_pandas_std():
    """Alternating +/-1% returns over 21d -> known std of log returns."""
    returns = pd.Series([0.01, -0.01] * 30)
    close = 100.0 * np.exp(returns.cumsum())
    rv = compute_realized_vol(close, window=21)
    log_returns = np.log(close / close.shift(1))
    expected = log_returns.iloc[-21:].std(ddof=1) * np.sqrt(252)
    assert rv.iloc[-1] == pytest.approx(expected, rel=1e-9)


def test_trailing_drawdown_from_rolling_peak():
    """Window=4 lets the peak roll off at the last bar — by index 6 the cohort
    is [100, 90, 95, 110], peak=110, dd=0. Production usage passes a large
    window (252); the small window here is required to exercise the
    roll-off branch with a 7-element fixture."""
    close = pd.Series([100.0, 110.0, 120.0, 100.0, 90.0, 95.0, 110.0])
    dd = compute_trailing_drawdown(close, window=4)
    expected = pd.Series([0.0, 0.0, 0.0, -20 / 120, -30 / 120, -25 / 120, 0.0])
    pd.testing.assert_series_equal(dd, expected, check_exact=False, rtol=1e-9)


# ---- Task 3.2: percentile rank with tie semantics ----


def test_percentile_rank_uses_prior_window_no_lookahead():
    s = pd.Series(range(1, 11), dtype=float)
    pr = compute_rolling_percentile_rank(s, window=5, tie_rule="strict_lt")
    assert pr.iloc[:4].isna().all()
    assert pr.iloc[4] == pytest.approx(1.0)
    assert pr.iloc[9] == pytest.approx(1.0)


def test_percentile_rank_constant_series_strict_lt_gives_zero():
    """v0.3 / CO-3: explicit tie semantics. strict_lt: ties -> 0."""
    s = pd.Series([5.0] * 10)
    pr = compute_rolling_percentile_rank(s, window=5, tie_rule="strict_lt")
    assert pr.iloc[:4].isna().all()
    assert pr.iloc[4:].eq(0.0).all()


def test_percentile_rank_constant_series_le_gives_one():
    s = pd.Series([5.0] * 10)
    pr = compute_rolling_percentile_rank(s, window=5, tie_rule="le")
    assert pr.iloc[:4].isna().all()
    assert pr.iloc[4:].eq(1.0).all()


def test_percentile_rank_unknown_tie_rule_raises():
    s = pd.Series(range(10), dtype=float)
    with pytest.raises(ValueError, match="tie_rule"):
        compute_rolling_percentile_rank(s, window=5, tie_rule="bogus")


# ---- Task 3.3: instantaneous classifier ----


THRESHOLDS_DEFAULT = {
    "P_SUPP": 0.30,
    "P_RO": 0.80,
    "P_PANIC": 0.95,
    "DD_EDR": 0.07,
    "NORMAL_LOW": 0.30,
    "NORMAL_HIGH": 0.80,
    "NORMAL_DD": 0.05,
}


def _row(vix_pct, vvix_pct, rv_pct, credit_pct, dd):
    return dict(
        vix_pct=vix_pct,
        vvix_pct=vvix_pct,
        rv_pct=rv_pct,
        credit_pct=credit_pct,
        dd=dd,
    )


def test_classify_normal_when_everything_mid_range():
    assert (
        classify_level1_instantaneous(
            _row(0.5, 0.5, 0.5, 0.5, -0.02), thresholds=THRESHOLDS_DEFAULT
        )
        == "NORMAL"
    )


def test_classify_suppressed_requires_all_below_p_supp():
    assert (
        classify_level1_instantaneous(
            _row(0.25, 0.20, 0.20, 0.15, -0.01), thresholds=THRESHOLDS_DEFAULT
        )
        == "SUPPRESSED"
    )


def test_classify_edr_when_drawdown_exceeds_threshold():
    assert (
        classify_level1_instantaneous(
            _row(0.6, 0.5, 0.5, 0.4, -0.10), thresholds=THRESHOLDS_DEFAULT
        )
        == "EDR"
    )


def test_classify_risk_off_via_credit_path():
    assert (
        classify_level1_instantaneous(
            _row(0.5, 0.5, 0.5, 0.85, -0.02), thresholds=THRESHOLDS_DEFAULT
        )
        == "RISK_OFF"
    )


def test_classify_risk_off_via_vol_path():
    assert (
        classify_level1_instantaneous(
            _row(0.85, 0.82, 0.5, 0.3, -0.02), thresholds=THRESHOLDS_DEFAULT
        )
        == "RISK_OFF"
    )


def test_classify_panic_requires_vix_and_rv_extreme():
    assert (
        classify_level1_instantaneous(
            _row(0.97, 0.85, 0.96, 0.85, -0.20), thresholds=THRESHOLDS_DEFAULT
        )
        == "PANIC"
    )


def test_class_precedence_panic_above_risk_off():
    assert (
        classify_level1_instantaneous(
            _row(0.98, 0.95, 0.99, 0.90, -0.05), thresholds=THRESHOLDS_DEFAULT
        )
        == "PANIC"
    )


def test_normal_band_widened_v0_3():
    """v0.3 / CO-4: NORMAL band [0.30, 0.80] eliminates the silent fall-through
    gap that existed in v0.2 with [0.25, 0.75]."""
    row = _row(0.32, 0.50, 0.50, 0.50, -0.02)
    assert classify_level1_instantaneous(row, thresholds=THRESHOLDS_DEFAULT) == "NORMAL"


# ---- Task 3.4: BOUNCE state machine ----


def test_bounce_opens_after_risk_off_ends():
    instant = ["NORMAL", "RISK_OFF", "RISK_OFF", "NORMAL", "NORMAL", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=3)
    assert out == ["NORMAL", "RISK_OFF", "RISK_OFF", "BOUNCE", "BOUNCE", "BOUNCE"]


def test_bounce_terminates_on_reactivation():
    instant = ["RISK_OFF", "NORMAL", "NORMAL", "RISK_OFF", "NORMAL", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=10)
    assert out == ["RISK_OFF", "BOUNCE", "BOUNCE", "RISK_OFF", "BOUNCE", "BOUNCE"]


def test_bounce_precedence_above_edr():
    instant = ["RISK_OFF", "EDR", "EDR", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=2)
    assert out == ["RISK_OFF", "BOUNCE", "BOUNCE", "NORMAL"]


def test_bounce_window_one_day():
    instant = ["PANIC", "NORMAL", "NORMAL"]
    out = apply_bounce_state_machine(instant, n_bounce=1)
    assert out == ["PANIC", "BOUNCE", "NORMAL"]


# ---- Task 3.5: derive_level1_frame ----


def test_derive_level1_frame_returns_components():
    history_pad = pd.date_range("2018-01-01", periods=260, freq="B")
    eval_dates = pd.date_range("2020-01-01", periods=30, freq="B")
    all_dates = history_pad.append(eval_dates)

    vix = pd.Series([15.0] * len(all_dates), index=all_dates)
    vvix = pd.Series([80.0] * len(all_dates), index=all_dates)
    spx = pd.Series([100.0] * len(all_dates), index=all_dates)
    credit = pd.Series([-1.0] * len(all_dates), index=all_dates)
    vix.loc["2020-01-15":"2020-01-17"] = 60.0
    vvix.loc["2020-01-15":"2020-01-17"] = 150.0

    thresholds = {
        "P_SUPP": 0.30,
        "P_RO": 0.80,
        "P_PANIC": 0.95,
        "DD_EDR": 0.07,
        "NORMAL_LOW": 0.30,
        "NORMAL_HIGH": 0.80,
        "NORMAL_DD": 0.05,
        "N_BOUNCE": 3,
        "rolling_window_days": 252,
        "realized_vol_window_days": 21,
        "percentile_tie_rule": "strict_lt",
    }
    frame = derive_level1_frame(
        vix=vix,
        vvix=vvix,
        spx=spx,
        credit_stress=credit,
        thresholds=thresholds,
    )
    assert set(
        [
            "truth_label",
            "instant_label",
            "vix_pct",
            "vvix_pct",
            "rv_pct",
            "credit_pct",
            "dd",
            "NFCI_value",
        ]
    ).issubset(frame.columns)
    eval_frame = frame.loc[eval_dates]
    assert "RISK_OFF" in eval_frame["truth_label"].values
    assert "BOUNCE" in eval_frame["truth_label"].values


def test_derive_level1_frame_persists_raw_nfci_value():
    """v0.3 / CL-3: raw NFCI value must be in the frame for replay determinism."""
    history_pad = pd.date_range("2018-01-01", periods=260, freq="B")
    vix = pd.Series([15.0] * len(history_pad), index=history_pad)
    vvix = pd.Series([80.0] * len(history_pad), index=history_pad)
    spx = pd.Series([100.0] * len(history_pad), index=history_pad)
    credit = pd.Series([-0.5] * len(history_pad), index=history_pad)
    credit.iloc[-1] = -0.3

    thresholds = {
        "P_SUPP": 0.30,
        "P_RO": 0.80,
        "P_PANIC": 0.95,
        "DD_EDR": 0.07,
        "NORMAL_LOW": 0.30,
        "NORMAL_HIGH": 0.80,
        "NORMAL_DD": 0.05,
        "N_BOUNCE": 3,
        "rolling_window_days": 252,
        "realized_vol_window_days": 21,
        "percentile_tie_rule": "strict_lt",
    }
    frame = derive_level1_frame(
        vix=vix,
        vvix=vvix,
        spx=spx,
        credit_stress=credit,
        thresholds=thresholds,
    )
    assert frame["NFCI_value"].iloc[-1] == pytest.approx(-0.3)
    assert frame["NFCI_value"].iloc[-2] == pytest.approx(-0.5)
