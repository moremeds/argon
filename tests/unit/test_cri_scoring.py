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
    # v3: floor lowered to 13. VIX 13 with no movement → both subscores 0
    assert score_vix_component(13.0, 0.0) == pytest.approx(0.0)


def test_score_vix_max_at_high_vix_and_roc() -> None:
    # v3: VIX >= 40 → level_score 15; RoC denom 40% → roc_score 10; total 25
    assert score_vix_component(40.0, 40.0) == pytest.approx(25.0)
    assert score_vix_component(99.0, 200.0) == pytest.approx(25.0)


def test_score_vix_nan_returns_zero() -> None:
    assert score_vix_component(float("nan"), 10.0) == 0.0
    assert score_vix_component(20.0, float("nan")) == 0.0


def test_score_vvix_zero_at_baseline() -> None:
    # v3: floor lowered to 80. VVIX 80, ratio 5.0, RoC 0 → all sub-scores 0
    assert score_vvix_component(80.0, 5.0, 0.0) == pytest.approx(0.0)


def test_score_vvix_max_at_extreme() -> None:
    # VVIX 130 → level 12; ratio 8 → ratio 7; RoC 25 → roc 6; total 25
    assert score_vvix_component(130.0, 8.0, 25.0) == pytest.approx(25.0)
    assert score_vvix_component(200.0, 10.0, 50.0) == pytest.approx(25.0)


def test_score_vvix_level_only() -> None:
    # v3: VVIX 110, ratio 5.0, RoC 0 → level only.
    # Derivation: (110-80)/50 * 12 = 30/50 * 12 = 7.2
    assert score_vvix_component(110.0, 5.0, 0.0) == pytest.approx(7.2, abs=0.01)


def test_score_vvix_roc_only() -> None:
    # v3: VVIX 80 (now the floor), ratio 5.0, RoC 12.5 → roc only.
    # Derivation: 12.5/25 * 6 = 3.0
    assert score_vvix_component(80.0, 5.0, 12.5) == pytest.approx(3.0, abs=0.01)


def test_score_vvix_roc_one_sided() -> None:
    # v3: at the new floor (80), negative RoC must still leave the score at 0
    assert score_vvix_component(80.0, 5.0, -50.0) == pytest.approx(0.0)


def test_score_vvix_nan_inputs() -> None:
    assert score_vvix_component(float("nan"), 5.0, 0.0) == 0.0
    assert score_vvix_component(95.0, float("nan"), 0.0) == 0.0
    # NaN RoC should be treated as 0, not zero-out the whole score.
    # v3 floor 80: VVIX 110 → level = (110-80)/50 * 12 = 7.2
    assert score_vvix_component(110.0, 5.0, float("nan")) == pytest.approx(
        7.2, abs=0.01
    )


def test_score_correlation_zero_below_threshold() -> None:
    assert score_correlation_component(25.0, 0.0) == pytest.approx(0.0)


def test_score_correlation_max() -> None:
    # COR1M 70 → level 17; 5d spike 20 → spike 8; total 25
    assert score_correlation_component(70.0, 20.0) == pytest.approx(25.0)


def test_score_momentum_zero_above_ma() -> None:
    # v3: pullback defaults to 0 → no tactical contribution either
    assert score_momentum_component(5.0) == 0.0
    assert score_momentum_component(0.0) == 0.0


def test_score_momentum_structural_max_at_minus_10() -> None:
    # v3: structural sub-score caps at 15 (not 25) — tactical pullback owns
    # the remaining 10 points.  Single-arg call → tactical=0, total=15.
    assert score_momentum_component(-10.0) == pytest.approx(15.0)
    assert score_momentum_component(-25.0) == pytest.approx(15.0)  # clipped


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
        vvix_vix_ratio=5.0,
        vvix_5d_roc=0.0,
        corr=20.0,
        corr_5d_change=0.0,
        spx_distance_pct=5.0,
    )
    assert out["score"] < 10
    assert out["level"] == "LOW"


def test_compute_cri_critical_market() -> None:
    # v3: must pass both structural (-12% MA) AND tactical pullback (-10% from
    # 20d high) to saturate the momentum component at 25.
    out = compute_cri(
        vix=40.0,
        vix_5d_roc=40.0,  # v3 denom 40 → 10/10
        vvix=130.0,
        vvix_vix_ratio=8.0,
        vvix_5d_roc=25.0,
        corr=70.0,
        corr_5d_change=20.0,
        spx_distance_pct=-12.0,
        pullback_20d_pct=-10.0,
    )
    assert out["score"] == pytest.approx(100.0)
    assert out["level"] == "CRITICAL"
    assert out["composite_version"] == 3
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


def test_run_analysis_prefers_spx_over_spy() -> None:
    """When both SPX and SPY are in aligned, SPX drives trend math."""
    n = 140
    aligned = {
        "VIX": np.full(n, 16.0),
        "VVIX": np.full(n, 95.0),
        "SPX": np.linspace(4500, 4800, n),  # SPX-scale levels
        "SPY": np.linspace(450, 480, n),  # SPY-scale levels (10x smaller)
        "COR1M": np.full(n, 20.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert out["spy"] > 4000, f"expected SPX-scale value, got {out['spy']}"
    assert out["spx_source"] == "SPX"


def test_run_analysis_falls_back_to_spy_when_spx_absent() -> None:
    """Without SPX, run_analysis still works with SPY (transition safety)."""
    n = 140
    aligned = {
        "VIX": np.full(n, 16.0),
        "VVIX": np.full(n, 95.0),
        "SPY": np.linspace(450, 480, n),
        "COR1M": np.full(n, 20.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert out["spy"] < 600, f"expected SPY-scale value, got {out['spy']}"
    assert out["spx_source"] == "SPY"


def test_run_analysis_exposes_mean_reversion_fields() -> None:
    """run_analysis must surface vrp, vix_zscore_30d, vix_vix3m_ratio, vix3m."""
    n = 140
    aligned = {
        "VIX": np.full(n, 20.0),
        "VVIX": np.full(n, 95.0),
        "SPX": np.linspace(4500, 4800, n),
        "VIX3M": np.full(n, 22.0),
        "COR1M": np.full(n, 30.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert "vrp" in out
    assert "vix_zscore_30d" in out
    assert "vix_vix3m_ratio" in out
    assert "vix3m" in out
    # VIX 20, VIX3M 22 → ratio ≈ 0.909 (contango)
    assert 0.8 < out["vix_vix3m_ratio"] < 1.0
    # Flat 20-VIX history → z-score = 0
    assert out["vix_zscore_30d"] == 0.0


def test_run_analysis_vrp_matches_vix_minus_realized_vol_exactly() -> None:
    """VIX − annualized 20d SPX RV; flat SPX → RV=0 → VRP = vix_now."""
    from uw_scan.cards.cri_scoring import VOL_WINDOW

    n = max(140, VOL_WINDOW + 50)
    aligned = {
        "VIX": np.full(n, 18.0),
        "VVIX": np.full(n, 95.0),
        "SPX": np.full(n, 4500.0),
        "VIX3M": np.full(n, 19.0),
        "COR1M": np.full(n, 20.0),
    }
    dates = [f"2024-{(i // 30) + 1:02d}-{(i % 30) + 1:02d}" for i in range(n)]
    out = run_analysis(aligned, dates)
    assert out["realized_vol"] == pytest.approx(0.0, abs=1e-9)
    assert out["vrp"] == pytest.approx(18.0, abs=0.01)
    assert out["vix_vix3m_ratio"] == pytest.approx(18.0 / 19.0, abs=1e-3)


# ══════════════════════════════════════════════════════════════════
# v3 calibration tests
# ══════════════════════════════════════════════════════════════════


class TestVixComponentV3:
    def test_floor_lowered_to_13(self) -> None:
        # VIX 13 → 0; VIX 14 → (14-13)/27 * 15 ≈ 0.556
        assert score_vix_component(13.0, 0.0) == 0.0
        score = score_vix_component(14.0, 0.0)
        assert abs(score - (15.0 / 27.0)) < 1e-6

    def test_roc_denominator_steepened_to_40(self) -> None:
        # RoC of 40% saturates the RoC sub-score at 10/10.
        # Derivation: max(40, 0)/40 * 10 = 10
        score = score_vix_component(13.0, 40.0)  # level=0 at floor, roc saturated
        assert abs(score - 10.0) < 1e-6


class TestVvixComponentV3:
    def test_floor_lowered_to_80(self) -> None:
        # With VVIX at the new floor (80), ratio at floor (5.0), zero RoC →
        # all three sub-scores are 0.
        assert score_vvix_component(80.0, 5.0, 0.0) == 0.0
        # VVIX 82 (above floor), ratio + RoC at floor.
        # Derivation: (82-80)/50 * 12 = 0.48
        score = score_vvix_component(82.0, 5.0, 0.0)
        assert abs(score - 0.48) < 1e-6


class TestMomentumComponentV3:
    def test_structural_break_capped_at_15(self) -> None:
        # SPX -10% below MA used to score 25; now caps at 15.
        # Derivation: abs(-10)/10 * 15 = 15
        score = score_momentum_component(spx_distance_pct=-10.0, pullback_20d_pct=0.0)
        assert abs(score - 15.0) < 1e-6

    def test_tactical_pullback_alone_can_fire_when_above_ma(self) -> None:
        # SPX +6% above MA → structural=0; -3% pullback → tactical = 3/4*10 = 7.5
        score = score_momentum_component(spx_distance_pct=6.0, pullback_20d_pct=-3.0)
        assert abs(score - 7.5) < 1e-6

    def test_tactical_pullback_saturates_at_minus_4pct(self) -> None:
        # Pullback of -6% (deeper than -4% saturation) → tactical capped at 10
        score = score_momentum_component(spx_distance_pct=0.0, pullback_20d_pct=-6.0)
        assert abs(score - 10.0) < 1e-6

    def test_total_capped_at_25(self) -> None:
        # structural=15 (capped) + tactical=10 (capped) = 25 (component cap)
        score = score_momentum_component(spx_distance_pct=-20.0, pullback_20d_pct=-10.0)
        assert abs(score - 25.0) < 1e-6

    def test_structural_15_plus_nonzero_tactical_below_cap(self) -> None:
        # Boundary case: structural saturated at 15, tactical=5 → total=20.
        # Catches a bug where the cap might short-circuit before adding tactical.
        score = score_momentum_component(spx_distance_pct=-10.0, pullback_20d_pct=-2.0)
        assert abs(score - 20.0) < 1e-6

    def test_today_real_world_scenario(self) -> None:
        # SPX +6.22% above MA → structural=0; -1.97% pullback → tactical = 1.97/4*10 = 4.925
        score = score_momentum_component(spx_distance_pct=6.22, pullback_20d_pct=-1.97)
        assert abs(score - 4.925) < 0.01


class TestCompositeVersionV3:
    def test_compute_cri_includes_composite_version_3(self) -> None:
        result = compute_cri(
            vix=18.0,
            vix_5d_roc=5.0,
            vvix=95.0,
            vvix_vix_ratio=5.3,
            vvix_5d_roc=2.0,
            corr=27.0,
            corr_5d_change=1.0,
            spx_distance_pct=6.0,
            pullback_20d_pct=-2.0,
        )
        assert result["composite_version"] == 3
        assert "momentum" in result["components"]


class TestRunAnalysisPayloadV3:
    def test_payload_includes_pullback_20d_pct_and_vix_delta_3d(self) -> None:
        # 110 closes; today is forced 2% below 3 sessions ago to ensure both
        # pullback and vix_delta inputs are non-trivial.
        n = 110
        spx = np.linspace(6000, 7000, n)
        spx[-1] = spx[-3] * 0.98
        vix = np.linspace(15, 18, n)
        vvix = np.linspace(85, 95, n)
        cor = np.full(n, 26.0)
        aligned = {
            "VIX": vix,
            "VVIX": vvix,
            "SPX": spx,
            "SPY": spx,
            "COR1M": cor,
        }
        dates = [f"2026-01-{(i % 28) + 1:02d}" for i in range(n)]
        out = run_analysis(aligned, dates)
        assert "pullback_20d_pct" in out
        assert "vix_delta_3d" in out
        assert out["pullback_20d_pct"] is not None and out["pullback_20d_pct"] < 0
        assert out["vix_delta_3d"] is not None
        assert out["cri"]["composite_version"] == 3

    def test_history_entries_include_pullback_20d_pct(self) -> None:
        # Each history entry must carry pullback_20d_pct so the UI prior-dot
        # for the tactical sub-score can be drawn.
        n = 130  # > 100 (MA window) + 20 (history window) + buffer
        aligned = {
            "VIX": np.full(n, 16.0),
            "VVIX": np.full(n, 95.0),
            "SPX": np.linspace(4500, 4800, n),
            "COR1M": np.full(n, 25.0),
        }
        dates = [f"2026-01-{(i % 28) + 1:02d}" for i in range(n)]
        out = run_analysis(aligned, dates)
        assert all("pullback_20d_pct" in row for row in out["history"])
