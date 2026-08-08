# tests/unit/test_magnet_calibration.py
import math

import numpy as np
import pytest

from uw_scan.reports.magnet_calibration import (
    NOMINAL_COVERAGE,
    coverage,
    pit,
    scale_estimates,
    standardized_residual,
)


def test_nominal_coverage_pairs_196_with_95_not_954():
    # 95.4% is the |z|<2 figure. Pairing it with 1.96 invents a 0.4pt miscalibration.
    assert NOMINAL_COVERAGE[1.96] == pytest.approx(0.9500, abs=5e-5)
    assert NOMINAL_COVERAGE[1.0] == pytest.approx(0.6827, abs=5e-5)


def test_standardized_residual_zero_at_risk_neutral_median():
    # Median log return under the model is -sigma^2 T / 2, which standardises to 0.
    sigma, h = 0.40, 5
    t = h / 252
    log_ret = -0.5 * sigma**2 * t
    assert standardized_residual(log_ret, sigma, h) == pytest.approx(0.0, abs=1e-12)


def test_standardized_residual_one_sigma_move():
    sigma, h = 0.40, 5
    t = h / 252
    log_ret = -0.5 * sigma**2 * t + sigma * math.sqrt(t)
    assert standardized_residual(log_ret, sigma, h) == pytest.approx(1.0, abs=1e-12)


def test_pit_of_zero_is_half():
    assert pit(np.array([0.0]))[0] == pytest.approx(0.5, abs=1e-12)


def test_coverage_counts_strictly_inside():
    z = np.array([-2.0, -0.5, 0.0, 0.5, 2.0])
    assert coverage(z, 1.0) == pytest.approx(3 / 5)


def test_scale_estimates_recover_unit_scale_on_standard_normal():
    rng = np.random.default_rng(20260808)
    z = rng.standard_normal(200_000)
    out = scale_estimates(z)
    assert out["std"] == pytest.approx(1.0, abs=0.01)
    assert out["mad"] == pytest.approx(1.0, abs=0.01)
    assert out["mean"] == pytest.approx(0.0, abs=0.01)
    assert out["n"] == 200_000


def test_scale_estimates_mad_ignores_fat_tail_that_moves_std():
    rng = np.random.default_rng(20260808)
    z = rng.standard_normal(100_000)
    z[:50] = 40.0  # 0.05% contamination
    out = scale_estimates(z)
    assert out["std"] > 1.05  # std is dragged
    assert out["mad"] == pytest.approx(1.0, abs=0.02)  # mad is not


def test_standardized_residual_rejects_non_positive_sigma():
    with pytest.raises(ValueError):
        standardized_residual(0.01, 0.0, 5)


from uw_scan.reports.magnet_calibration import (  # noqa: E402
    moving_block_bootstrap,
    nonoverlapping_subsample,
    panel_block_bootstrap,
)


def test_nonoverlapping_subsample_takes_every_step():
    v = np.arange(10.0)
    assert nonoverlapping_subsample(v, 5).tolist() == [0.0, 5.0]
    assert nonoverlapping_subsample(v, 5, offset=2).tolist() == [2.0, 7.0]


def test_bootstrap_ci_brackets_the_point_estimate():
    rng = np.random.default_rng(1)
    v = rng.standard_normal(2000)
    out = moving_block_bootstrap(v, np.mean, block=5, n_boot=400, seed=7)
    assert out["lo"] < out["point"] < out["hi"]
    assert out["n_boot"] == 400
    assert out["block"] == 5


def test_bootstrap_is_deterministic_under_a_fixed_seed():
    rng = np.random.default_rng(2)
    v = rng.standard_normal(500)
    a = moving_block_bootstrap(v, np.mean, block=5, n_boot=200, seed=42)
    b = moving_block_bootstrap(v, np.mean, block=5, n_boot=200, seed=42)
    assert a == b


def test_bootstrap_ci_is_wider_for_longer_blocks():
    # Overlap-induced dependence: longer blocks retain more of it, so the CI
    # must not shrink. This is the whole reason the plain CI is banned.
    rng = np.random.default_rng(3)
    v = np.convolve(rng.standard_normal(4000), np.ones(5) / 5, mode="same")
    narrow = moving_block_bootstrap(v, np.mean, block=1, n_boot=400, seed=11)
    wide = moving_block_bootstrap(v, np.mean, block=20, n_boot=400, seed=11)
    assert (wide["hi"] - wide["lo"]) > (narrow["hi"] - narrow["lo"])


def test_bootstrap_rejects_block_longer_than_sample():
    with pytest.raises(ValueError):
        moving_block_bootstrap(np.arange(5.0), np.mean, block=10, n_boot=10, seed=1)


def _panel(n_dates: int, n_tickers: int, rho: float, seed: int):
    """z-panel where every ticker shares a same-day common factor of strength rho
    and every ticker has the SAME true scale. Any per-ticker dispersion measured
    on this is estimation noise, by construction."""
    rng = np.random.default_rng(seed)
    common = rng.standard_normal(n_dates)
    dates, vals = [], []
    for _ in range(n_tickers):
        idio = rng.standard_normal(n_dates)
        z = math.sqrt(rho) * common + math.sqrt(1 - rho) * idio
        dates.extend(range(n_dates))
        vals.extend(z.tolist())
    return np.array(dates), np.array(vals)


def _k(a: np.ndarray) -> float:
    return float(np.std(a, ddof=1))


def test_panel_bootstrap_matches_naive_when_tickers_are_independent():
    dates, vals = _panel(161, 40, rho=0.0, seed=42)
    naive = moving_block_bootstrap(vals, _k, block=5, n_boot=400, seed=7)
    panel = panel_block_bootstrap(dates, vals, _k, block=5, n_boot=400, seed=7)
    nw, pw = naive["hi"] - naive["lo"], panel["hi"] - panel["lo"]
    assert pw == pytest.approx(nw, rel=0.35)


def test_panel_bootstrap_is_much_wider_under_cross_sectional_correlation():
    """The G3 guard. Measured ratios: 2.99x at rho=0.3, 6.10x at rho=0.6,
    9.33x at rho=0.9. If this ever collapses toward 1.0, the panel bootstrap has
    stopped preserving the common factor and G3 is corrupt again."""
    dates, vals = _panel(161, 114, rho=0.6, seed=42)
    naive = moving_block_bootstrap(vals, _k, block=5, n_boot=400, seed=7)
    panel = panel_block_bootstrap(dates, vals, _k, block=5, n_boot=400, seed=7)
    assert (panel["hi"] - panel["lo"]) > 3.0 * (naive["hi"] - naive["lo"])


def test_naive_bootstrap_would_pass_G3_on_a_panel_with_no_real_dispersion():
    """Regression test for the actual bug, stated as the decision it corrupts.

    Every ticker here has the same true k. G3 must say 'pooled constant'. The
    naive CI is ~6x too narrow and flips that to 'build a per-ticker table'.
    """
    dates, vals = _panel(161, 114, rho=0.6, seed=42)
    per_ticker_k = [_k(vals[dates == d]) for d in range(0)] or [
        _k(vals[i * 161 : (i + 1) * 161]) for i in range(114)
    ]
    dispersion = float(np.std(per_ticker_k, ddof=1))

    naive_w = (lambda b: b["hi"] - b["lo"])(
        moving_block_bootstrap(vals, _k, block=5, n_boot=400, seed=7)
    )
    panel_w = (lambda b: b["hi"] - b["lo"])(
        panel_block_bootstrap(dates, vals, _k, block=5, n_boot=400, seed=7)
    )
    assert dispersion > naive_w, "the naive CI is narrow enough to fire G3 wrongly"
    assert dispersion < panel_w, "the panel CI must correctly suppress G3 here"


def test_panel_bootstrap_rejects_block_longer_than_the_date_axis():
    dates, vals = _panel(4, 10, rho=0.0, seed=1)
    with pytest.raises(ValueError):
        panel_block_bootstrap(dates, vals, _k, block=10, n_boot=10, seed=1)
