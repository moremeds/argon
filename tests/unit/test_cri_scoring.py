"""Unit tests for CRI pure scoring functions."""

import math

import numpy as np
import pytest

from uw_scan.cards.cri_scoring import (
    compute_cri,
    compute_realized_vol,
    cor1m_level_and_change,
    crash_trigger,
    cri_level,
    cta_exposure_model,
    run_analysis,
    score_correlation_component,
    score_momentum_component,
    score_vix_component,
    score_vvix_component,
)

# ── component scorers ──────────────────────────────────────────────


def test_score_vix_zero_when_calm() -> None:
    # VIX 15 with no movement → both subscores 0
    assert score_vix_component(15.0, 0.0) == pytest.approx(0.0)


def test_score_vix_max_at_high_vix_and_roc() -> None:
    # VIX >= 40 → level_score 15; RoC >= 60% → roc_score 10; total 25
    assert score_vix_component(40.0, 60.0) == pytest.approx(25.0)
    assert score_vix_component(99.0, 200.0) == pytest.approx(25.0)


def test_score_vix_nan_returns_zero() -> None:
    assert score_vix_component(float("nan"), 10.0) == 0.0
    assert score_vix_component(20.0, float("nan")) == 0.0


def test_score_vvix_zero_at_baseline() -> None:
    assert score_vvix_component(90.0, 5.0) == pytest.approx(0.0)


def test_score_vvix_max_at_extreme() -> None:
    # VVIX 140 → level 17; ratio 8 → ratio 8; total 25
    assert score_vvix_component(140.0, 8.0) == pytest.approx(25.0)


def test_score_correlation_zero_below_threshold() -> None:
    assert score_correlation_component(25.0, 0.0) == pytest.approx(0.0)


def test_score_correlation_max() -> None:
    # COR1M 70 → level 17; 5d spike 20 → spike 8; total 25
    assert score_correlation_component(70.0, 20.0) == pytest.approx(25.0)


def test_score_momentum_zero_above_ma() -> None:
    assert score_momentum_component(5.0) == 0.0
    assert score_momentum_component(0.0) == 0.0


def test_score_momentum_max_at_minus_10() -> None:
    # -10% distance → full 25
    assert score_momentum_component(-10.0) == pytest.approx(25.0)
    assert score_momentum_component(-25.0) == pytest.approx(25.0)  # clipped


def test_score_momentum_nan_returns_zero() -> None:
    assert score_momentum_component(float("nan")) == 0.0


# ── composite / level ─────────────────────────────────────────────


def test_cri_level_thresholds() -> None:
    assert cri_level(0.0) == "LOW"
    assert cri_level(24.9) == "LOW"
    assert cri_level(25.0) == "ELEVATED"
    assert cri_level(49.9) == "ELEVATED"
    assert cri_level(50.0) == "HIGH"
    assert cri_level(74.9) == "HIGH"
    assert cri_level(75.0) == "CRITICAL"
    assert cri_level(100.0) == "CRITICAL"


def test_compute_cri_calm_market_low() -> None:
    out = compute_cri(
        vix=14.0,
        vix_5d_roc=0.0,
        vvix=85.0,
        vvix_vix_ratio=6.0,
        corr=20.0,
        corr_5d_change=0.0,
        spx_distance_pct=5.0,
    )
    assert out["score"] < 10
    assert out["level"] == "LOW"


def test_compute_cri_critical_market() -> None:
    out = compute_cri(
        vix=40.0,
        vix_5d_roc=60.0,
        vvix=140.0,
        vvix_vix_ratio=8.0,
        corr=70.0,
        corr_5d_change=20.0,
        spx_distance_pct=-12.0,
    )
    assert out["score"] == pytest.approx(100.0)
    assert out["level"] == "CRITICAL"
    assert set(out["components"].keys()) == {"vix", "vvix", "correlation", "momentum"}


# ── realized vol ──────────────────────────────────────────────────


def test_realized_vol_nan_for_short_series() -> None:
    assert math.isnan(compute_realized_vol(np.array([100.0, 101.0]), window=20))


def test_realized_vol_returns_finite_for_long_series() -> None:
    # 30 daily closes with ~1% std → ~16% annualized
    np.random.seed(0)
    closes = np.cumprod(1 + np.random.normal(0, 0.01, 30)) * 100
    rv = compute_realized_vol(closes, window=20)
    assert math.isfinite(rv)
    assert 5.0 < rv < 40.0


# ── cor1m helper ──────────────────────────────────────────────────


def test_cor1m_empty_returns_nan() -> None:
    cur, chg = cor1m_level_and_change(np.array([]))
    assert math.isnan(cur)
    assert math.isnan(chg)


def test_cor1m_change_over_5_sessions() -> None:
    arr = np.array([10.0, 12.0, 14.0, 16.0, 18.0, 20.0])  # 6 values; -6 is 10
    cur, chg = cor1m_level_and_change(arr)
    assert cur == pytest.approx(20.0)
    assert chg == pytest.approx(10.0)


# ── cta + crash trigger ───────────────────────────────────────────


def test_cta_exposure_below_target_max_exposure() -> None:
    # Realized vol 5% (well below 10% target) → 200% capped exposure
    out = cta_exposure_model(realized_vol=5.0)
    assert out["exposure_pct"] == pytest.approx(200.0)
    assert out["forced_reduction"] is False


def test_cta_exposure_high_vol_forces_reduction() -> None:
    # Realized vol 25% → 40% exposure → 60% reduction
    out = cta_exposure_model(realized_vol=25.0)
    assert out["exposure_pct"] == pytest.approx(40.0)
    assert out["forced_reduction"] is True
    assert out["forced_reduction_pct"] == pytest.approx(60.0)
    assert out["est_selling_bn"] > 0


def test_crash_trigger_fires_when_all_three() -> None:
    out = crash_trigger(spx_below_ma=True, realized_vol=30.0, cor1m=65.0)
    assert out["fired"] is True


def test_crash_trigger_silent_when_only_one() -> None:
    out = crash_trigger(spx_below_ma=False, realized_vol=30.0, cor1m=65.0)
    assert out["fired"] is False


# ── full run_analysis orchestration ───────────────────────────────


def _make_aligned(n: int = 120) -> tuple[dict[str, np.ndarray], list[str]]:
    """Synthetic, calm-market arrays — vix ~16, vvix ~95, spy trending up."""
    from datetime import date, timedelta

    days = [(date(2026, 1, 1) + timedelta(days=i)).isoformat() for i in range(n)]
    aligned = {
        "VIX": np.full(n, 16.0),
        "VVIX": np.full(n, 95.0),
        "SPY": np.linspace(450, 600, n),
        "COR1M": np.full(n, 20.0),
    }
    return aligned, days


def test_run_analysis_calm_market_yields_low_cri() -> None:
    aligned, dates = _make_aligned()
    out = run_analysis(aligned, dates)
    assert out["cri"]["level"] == "LOW"
    assert out["cri"]["score"] < 25
    assert out["crash_trigger"]["fired"] is False
    assert len(out["history"]) == 20
    assert len(out["spy_closes"]) == 40  # VOL_WINDOW * 2


def test_run_analysis_history_dates_monotonic() -> None:
    aligned, dates = _make_aligned()
    out = run_analysis(aligned, dates)
    hist_dates = [h["date"] for h in out["history"]]
    assert hist_dates == sorted(hist_dates)


def test_run_analysis_exposes_vvix_5d_roc() -> None:
    """run_analysis should emit vvix_5d_roc alongside vix_5d_roc."""
    n = 140
    aligned = {
        "VIX": np.full(n, 18.0),
        "VVIX": np.linspace(80.0, 100.0, n),  # rising ~25% over the full window
        "SPY": np.full(n, 500.0),
        "COR1M": np.full(n, 30.0),
    }
    common_dates = [f"2024-01-{i:02d}" for i in range(1, n + 1)]
    payload = run_analysis(aligned, common_dates)
    assert "vvix_5d_roc" in payload
    # Last 5 sessions of a 140-step linspace 80→100: 0.7%-ish RoC
    assert 0.0 < payload["vvix_5d_roc"] < 2.0
    # Per-row history must also carry the new fields used by the UI prior-dot
    last_row = payload["history"][-1]
    assert "vvix_5d_roc" in last_row
    assert "cor1m_5d_change" in last_row
