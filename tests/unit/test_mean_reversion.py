"""Unit tests for VRP / z-score / term-structure helpers."""

import math

import numpy as np
import pytest
from uw_scan.cards.mean_reversion import (
    compute_vrp,
    vix_vix3m_ratio,
    vix_zscore_30d,
)


def test_compute_vrp_positive_when_iv_exceeds_rv() -> None:
    # VIX 20, RV 12 → VRP = +8
    assert compute_vrp(vix=20.0, realized_vol=12.0) == pytest.approx(8.0)


def test_compute_vrp_negative_when_rv_exceeds_iv() -> None:
    # VIX 15, RV 22 → VRP = -7 (rare but happens after a sudden spike)
    assert compute_vrp(vix=15.0, realized_vol=22.0) == pytest.approx(-7.0)


def test_compute_vrp_nan_inputs_return_nan() -> None:
    assert math.isnan(compute_vrp(vix=float("nan"), realized_vol=10.0))
    assert math.isnan(compute_vrp(vix=20.0, realized_vol=float("nan")))


def test_vix_zscore_returns_zero_for_flat_history() -> None:
    arr = np.full(60, 18.0)
    assert vix_zscore_30d(arr) == pytest.approx(0.0)


def test_vix_zscore_returns_nan_when_trailing_std_is_zero_and_today_differs() -> None:
    # 30 trailing days at 15 + today at 25. ZSCORE_WINDOW=30 requires
    # ZSCORE_WINDOW+1 = 31 observations total (30 trailing + 1 today). The
    # trailing window has zero std (all 15s) so the function returns NaN
    # per its degenerate-input contract.
    arr = np.concatenate([np.full(30, 15.0), np.array([25.0])])
    assert math.isnan(vix_zscore_30d(arr))


def test_vix_zscore_positive_when_today_above_noisy_mean() -> None:
    # 30 trailing days drawn from mean≈15 std≈1 (so the std is non-zero),
    # then today at 25 → z ≈ 10. Use a fixed seed so the test is deterministic.
    rng = np.random.default_rng(seed=42)
    trailing = rng.normal(loc=15.0, scale=1.0, size=30)
    arr = np.concatenate([trailing, np.array([25.0])])
    z = vix_zscore_30d(arr)
    assert z > 2.0


def test_vix_zscore_nan_for_short_series() -> None:
    # Exactly ZSCORE_WINDOW observations is still insufficient — we need
    # ZSCORE_WINDOW + 1 (trailing window + today).
    arr = np.full(30, 18.0)
    assert math.isnan(vix_zscore_30d(arr))


def test_vix_vix3m_ratio_contango_below_1() -> None:
    # Normal day: VIX 15, VIX3M 17 → ratio 0.88 (contango)
    assert vix_vix3m_ratio(vix=15.0, vix3m=17.0) == pytest.approx(15.0 / 17.0)


def test_vix_vix3m_ratio_backwardation_above_1() -> None:
    # Stress day: VIX 30, VIX3M 25 → ratio 1.2 (backwardation)
    assert vix_vix3m_ratio(vix=30.0, vix3m=25.0) == pytest.approx(1.2)


def test_vix_vix3m_ratio_nan_on_missing_vix3m() -> None:
    assert math.isnan(vix_vix3m_ratio(vix=18.0, vix3m=float("nan")))
    assert math.isnan(vix_vix3m_ratio(vix=18.0, vix3m=0.0))
