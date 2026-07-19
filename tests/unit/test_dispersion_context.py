"""Unit tests for the dispersion-context ratio z-score helper (pure math)."""

from __future__ import annotations

from uw_scan.storage.vol_index_repository import _ratio_zscore


def test_too_few_points_returns_none():
    assert _ratio_zscore([1.0, 2.0]) is None


def test_under_thirty_prior_returns_none():
    assert _ratio_zscore([1.0] * 20 + [5.0]) is None


def test_zero_variance_prior_returns_none():
    # 40 identical priors -> pstdev == 0 -> cannot standardise
    assert _ratio_zscore([1.0] * 40 + [2.0]) is None


def test_positive_zscore():
    # prior alternates 1.0/2.0 (mean 1.5, pstdev 0.5); latest 2.5 -> z = +2.0
    ratios = [1.0, 2.0] * 20 + [2.5]
    z = _ratio_zscore(ratios)
    assert z is not None and abs(z - 2.0) < 1e-9


def test_negative_zscore():
    ratios = [1.0, 2.0] * 20 + [0.5]  # latest below mean -> z = -2.0
    z = _ratio_zscore(ratios)
    assert z is not None and abs(z + 2.0) < 1e-9


def test_window_excludes_latest():
    # latest must not pull its own mean; a lone huge latest still scores high
    ratios = [1.0, 1.02] * 130 + [3.0]  # ~260 prior points with small variance
    z = _ratio_zscore(ratios)
    assert z is not None and z > 50  # far above the tight prior band
