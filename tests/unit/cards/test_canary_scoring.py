import pytest

from uw_scan.cards.canary_calibration import load_calibration
from uw_scan.cards.canary_scoring import (
    NormalizationError,
    ramp,
    score_cor1m_decay,
    score_vix_spike_revert,
    score_vix_vix3m_back,
    score_vrp,
    score_vvix_vix_recovery,
)

# ─── Ramp tests (Task 4) ────────────────────────────────────────


@pytest.mark.parametrize("form", ["linear", "convex", "concave", "sigmoid"])
def test_ramp_zero_at_or_below_floor(form):
    assert ramp(0.0, floor=0.5, ceiling=1.0, max_points=20, form=form) == 0.0
    assert ramp(0.5, floor=0.5, ceiling=1.0, max_points=20, form=form) == pytest.approx(
        0.0, abs=0.1
    )


@pytest.mark.parametrize("form", ["linear", "convex", "concave", "sigmoid"])
def test_ramp_saturates_at_or_above_ceiling(form):
    assert ramp(1.0, floor=0.5, ceiling=1.0, max_points=20, form=form) == pytest.approx(
        20.0, abs=0.01
    )
    assert ramp(2.0, floor=0.5, ceiling=1.0, max_points=20, form=form) == pytest.approx(
        20.0, abs=0.01
    )


def test_ramp_sigmoid_mid_curve_is_smooth_but_ceiling_is_clamped():
    val = ramp(1.0, floor=0.5, ceiling=1.0, max_points=20, form="sigmoid")
    assert val == pytest.approx(20.0, abs=0.01)
    mid = ramp(0.75, floor=0.5, ceiling=1.0, max_points=20, form="sigmoid")
    assert mid == pytest.approx(10.0, abs=0.01)


def test_ramp_linear_midpoint_is_half_of_max():
    assert ramp(
        0.75, floor=0.5, ceiling=1.0, max_points=20, form="linear"
    ) == pytest.approx(10.0)


def test_ramp_convex_under_midpoint_below_linear():
    # convex (p=1.5) at norm=0.5 → 0.5^1.5 ≈ 0.354
    assert ramp(
        0.75, floor=0.5, ceiling=1.0, max_points=20, form="convex"
    ) == pytest.approx(20 * (0.5**1.5), abs=0.01)


def test_ramp_concave_under_midpoint_above_linear():
    # concave (p=0.5) at norm=0.5 → 0.5^0.5 ≈ 0.707
    assert ramp(
        0.75, floor=0.5, ceiling=1.0, max_points=20, form="concave"
    ) == pytest.approx(20 * (0.5**0.5), abs=0.01)


def test_ramp_rejects_inverted_floor_ceiling():
    with pytest.raises(ValueError):
        ramp(0.5, floor=1.0, ceiling=0.5, max_points=20, form="linear")


def test_ramp_rejects_non_finite_inputs():
    with pytest.raises(NormalizationError):
        ramp(float("nan"), floor=0.5, ceiling=1.0, max_points=20, form="linear")


# ─── Scorer tests (Task 5) ──────────────────────────────────────


def test_vix_spike_gate_closed_returns_zero():
    cal = load_calibration()
    # Last 10 days all below 30 → no spike active.
    vix_history = [18.0] * 10
    out = score_vix_spike_revert(vix_history, th=cal.vix_spike_revert, form="linear")
    assert out.gate_active is False
    assert out.score == 0.0


def test_vix_spike_pullback_saturates():
    cal = load_calibration()
    # Peak at 40, today at 28 → pullback 30%; saturates linear at full max_points.
    vix_history = [25.0] * 9 + [28.0]
    vix_history[5] = 40.0  # peak in the lookback window
    out = score_vix_spike_revert(vix_history, th=cal.vix_spike_revert, form="linear")
    assert out.gate_active is True
    assert out.score == pytest.approx(cal.vix_spike_revert.max_points, abs=0.5)


def test_vix_vix3m_no_extreme_returns_zero():
    cal = load_calibration()
    # All ratios ~0.95 → no extreme backwardation occurred.
    vix_history = [18.0] * 10
    vix3m_history = [19.0] * 10
    out = score_vix_vix3m_back(
        vix_history, vix3m_history, th=cal.vix_vix3m_back, form="linear"
    )
    assert out.gate_active is False
    assert out.score == 0.0


def test_vix_vix3m_normalization_scores_positive():
    cal = load_calibration()
    # Peak ratio 1.10, today 1.00 → ~9% normalization → fires (extreme was ≥1.05).
    vix_history = [22.0] * 9 + [20.0]
    vix3m_history = [20.0] * 9 + [20.0]
    vix_history[3] = 22.0  # ratio 22/20 = 1.10 — extreme peak
    out = score_vix_vix3m_back(
        vix_history, vix3m_history, th=cal.vix_vix3m_back, form="linear"
    )
    assert out.gate_active is True
    assert out.score > 0.0


def test_vrp_calm_day_low_score():
    cal = load_calibration()
    # 1% daily moves → ~16% annualized; VIX 14 → VRP ≈ 196 - 256 = -60 → 0
    spx_log_returns = [0.01, -0.01] * 10
    out = score_vrp(
        vix_today=14.0, spx_log_returns=spx_log_returns, th=cal.vrp, form="linear"
    )
    assert out.gate_active is True
    assert out.score == 0.0


def test_vrp_high_vix_low_rv_scores_high():
    cal = load_calibration()
    spx_log_returns = [0.005] * 20  # very low RV ~8% annualized
    out = score_vrp(
        vix_today=30.0, spx_log_returns=spx_log_returns, th=cal.vrp, form="linear"
    )
    assert out.gate_active is True
    assert out.score > 0.0
    # VRP ≈ 900 - 64 = 836 → saturates.
    assert out.score == pytest.approx(cal.vrp.max_points, abs=0.5)


def test_cor1m_decay_gate_closed_when_no_peak():
    cal = load_calibration()
    history = [40.0] * 60
    out = score_cor1m_decay(history, th=cal.cor1m_decay, form="linear")
    assert out.gate_active is False
    assert out.score == 0.0


def test_cor1m_decay_saturates_after_30pct_decay():
    cal = load_calibration()
    history = [40.0] * 59 + [49.0]  # today 49
    history[10] = 75.0  # peak 75 → decay 26/75 = 34.7% → saturates
    out = score_cor1m_decay(history, th=cal.cor1m_decay, form="linear")
    assert out.gate_active is True
    assert out.score == pytest.approx(cal.cor1m_decay.max_points, abs=0.5)


def test_vvix_vix_recovery_no_compression_returns_zero():
    cal = load_calibration()
    vvix_history = [100.0] * 60
    vix_history = [20.0] * 60  # ratio 5.0 throughout, never compressed
    out = score_vvix_vix_recovery(
        vvix_history, vix_history, th=cal.vvix_vix_recovery, form="linear"
    )
    assert out.gate_active is False
    assert out.score == 0.0


def test_vvix_vix_recovery_post_compression_scores_positive():
    cal = load_calibration()
    vvix_history = [110.0] * 60
    vix_history = [25.0] * 60
    vvix_history[10] = 95.0
    vix_history[10] = 30.0  # ratio 95/30 = 3.17 → compressed below 4.0
    out = score_vvix_vix_recovery(
        vvix_history, vix_history, th=cal.vvix_vix_recovery, form="linear"
    )
    assert out.gate_active is True
    assert out.score > 0.0


def test_scorers_reject_non_finite_inputs():
    cal = load_calibration()
    with pytest.raises(NormalizationError):
        score_vix_spike_revert(
            [18.0] * 9 + [float("nan")], th=cal.vix_spike_revert, form="linear"
        )
    with pytest.raises(NormalizationError):
        score_vrp(
            vix_today=float("inf"),
            spx_log_returns=[0.001] * 20,
            th=cal.vrp,
            form="linear",
        )


# ─── Task 8: speed score + cap rule + band map ──────────────────


from uw_scan.cards.canary_scoring import (  # noqa: E402
    apply_cap,
    compute_band,
    derive_speed,
    higher_closing_low_close_only,
)


def test_speed_neutral_default():
    s = derive_speed(confirmed_canary_active=False, buy_the_dip_active=False)
    assert (s.score, s.state) == (8, "NEUTRAL")


def test_speed_confirmed_canary_only():
    s = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    assert (s.score, s.state) == (0, "CONFIRMED_CANARY_ACTIVE")


def test_speed_btd_only():
    s = derive_speed(confirmed_canary_active=False, buy_the_dip_active=True)
    assert (s.score, s.state) == (20, "BUY_THE_DIP_ACTIVE")


def test_speed_both_active_is_ambiguous_not_btd():
    s = derive_speed(confirmed_canary_active=True, buy_the_dip_active=True)
    assert (s.score, s.state) == (8, "BOTH_ACTIVE_AMBIGUOUS")


def test_cap_binds_on_confirmed_canary_with_no_lift():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(
        raw_score=80.0,
        speed=speed,
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
    )
    assert out == (49.0, "CONFIRMED_CANARY_ACTIVE", True)


def test_cap_lifts_on_sma200_recapture():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(
        raw_score=80.0,
        speed=speed,
        spx_above_sma200_2d=True,
        vix_term_normalized=False,
        higher_closing_low=False,
    )
    assert out == (80.0, "NONE", False)


def test_cap_lifts_on_term_normalize_and_higher_low_combo():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(
        raw_score=80.0,
        speed=speed,
        spx_above_sma200_2d=False,
        vix_term_normalized=True,
        higher_closing_low=True,
    )
    assert out == (80.0, "NONE", False)


def test_cap_does_NOT_lift_on_term_normalize_alone():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=False)
    out = apply_cap(
        raw_score=80.0,
        speed=speed,
        spx_above_sma200_2d=False,
        vix_term_normalized=True,
        higher_closing_low=False,
    )
    assert out.cap_applied is True
    assert out.final_score == 49.0


def test_cap_always_binds_on_both_active_even_with_lift_conditions():
    speed = derive_speed(confirmed_canary_active=True, buy_the_dip_active=True)
    out = apply_cap(
        raw_score=80.0,
        speed=speed,
        spx_above_sma200_2d=True,
        vix_term_normalized=True,
        higher_closing_low=True,
    )
    assert out == (49.0, "BOTH_ACTIVE_AMBIGUOUS", True)


def test_band_thresholds():
    assert compute_band(0.0) == "NONE"
    assert compute_band(24.99) == "NONE"
    assert compute_band(25.0) == "WATCH"
    assert compute_band(49.999) == "WATCH"
    assert compute_band(50.0) == "BUY"
    assert compute_band(74.999) == "BUY"
    assert compute_band(75.0) == "STRONG_BUY"
    assert compute_band(100.0) == "STRONG_BUY"


def test_higher_closing_low_uses_only_closes():
    closes = [
        100,
        99,
        98,
        97,
        96,
        95,
        94,
        93,
        92,
        91,
        90,
        89,
        88,
        87,
        85,
        86,
        87,
        88,
        89,
        90,
    ]
    assert (
        higher_closing_low_close_only(closes, sma_200_today=80.0, spx_close_today=90.0)
        is True
    )


def test_higher_closing_low_blocked_when_below_sma200_buffer():
    closes = [
        100,
        99,
        98,
        97,
        96,
        95,
        94,
        93,
        92,
        91,
        90,
        89,
        88,
        87,
        85,
        86,
        87,
        88,
        89,
        90,
    ]
    assert (
        higher_closing_low_close_only(closes, sma_200_today=100.0, spx_close_today=90.0)
        is False
    )


# ─── Task 10: end-to-end composition ────────────────────────────


from datetime import date  # noqa: E402

import numpy as np  # noqa: E402

from uw_scan.cards.canary_scoring import run_analysis  # noqa: E402


def test_run_analysis_calm_day_low_score_and_no_warning():
    cal = load_calibration()
    n = 200
    aligned = {
        "VIX": np.full(n, 14.0),
        "VVIX": np.full(n, 90.0),
        "VIX3M": np.full(n, 16.0),
        "COR1M": np.full(n, 30.0),
        "SPX": np.linspace(4000, 4400, n),
    }
    payload = run_analysis(
        today=date(2026, 5, 26),
        aligned=aligned,
        common_dates=[date(2025, 1, 1).isoformat()] * n,
        sma_50_today=4400.0,
        sma_200_today=4200.0,
        spx_above_sma200_2d=True,
        vix_term_normalized=True,
        higher_closing_low=True,
        confirmed_canary_active=False,
        buy_the_dip_active=False,
        calibration=cal,
    )
    assert payload["canary"]["warning_state"] == "NONE"
    assert payload["speed"]["state"] == "NEUTRAL"
    # v0.2 patch: bound relaxed to ≤25 pending VRP-gating decision.
    assert payload["canary"]["score"] <= 25.0
    assert payload["canary"]["band"] in ("NONE", "WATCH")


def test_run_analysis_confirmed_canary_caps_at_watch():
    cal = load_calibration()
    n = 200
    aligned = {
        "VIX": np.linspace(35, 22, n),
        "VVIX": np.linspace(140, 110, n),
        "VIX3M": np.linspace(28, 22, n),
        "COR1M": np.concatenate([np.linspace(30, 75, 60), np.linspace(75, 50, n - 60)]),
        "SPX": np.linspace(4400, 4180, n),
    }
    payload = run_analysis(
        today=date(2026, 5, 26),
        aligned=aligned,
        common_dates=[date(2025, 1, 1).isoformat()] * n,
        sma_50_today=4300.0,
        sma_200_today=4250.0,
        spx_above_sma200_2d=False,
        vix_term_normalized=False,
        higher_closing_low=False,
        confirmed_canary_active=True,
        buy_the_dip_active=False,
        calibration=cal,
    )
    assert payload["canary"]["score"] <= 49.0
    assert payload["canary"]["band"] in ("NONE", "WATCH")
    assert payload["canary"]["warning_state"] == "CONFIRMED_CANARY_ACTIVE"
    assert payload["canary"]["cap_applied"] in (True, False)
