"""Pin every frozen v13 constant. A drift here is a different model wearing the same name."""

from uw_scan.density.constants import (
    BAND_80,
    EWMA_LAMBDA,
    GJR_MIN_OBS,
    H_MAX,
    HORIZONS,
    LAM,
    LOGLIK_TOL,
    M_PATHS,
    MAX_FAILURE_CARRY_DAYS,
    MULTI_STARTS,
    OVERLAY_BURN_IN,
    OVERLAY_MIN_POOL,
    PANEL_SHA256,
    QUANTILES,
    SEED_BASE,
    T_START_NU,
    V5_ANCHOR,
    seed_for,
)


def test_frozen_constants() -> None:
    assert QUANTILES == (0.05, 0.10, 0.25, 0.50, 0.75, 0.90, 0.95)
    assert BAND_80 == (1, 5)
    assert (GJR_MIN_OBS, OVERLAY_BURN_IN, OVERLAY_MIN_POOL) == (756, 252, 756)
    assert (M_PATHS, H_MAX, HORIZONS) == (10000, 5, (1, 2, 3, 5))
    assert LAM == 0.94 and EWMA_LAMBDA == 0.94
    assert (V5_ANCHOR, SEED_BASE) == (755, 20260728)
    assert MULTI_STARTS == (
        (0.05, 0.05, 0.05, 0.85),
        (0.02, 0.02, 0.02, 0.90),
        (0.10, 0.10, 0.10, 0.70),
        (0.20, 0.01, 0.15, 0.60),
    )
    assert T_START_NU == 8.0
    assert (MAX_FAILURE_CARRY_DAYS, LOGLIK_TOL) == (10, 1e-6)
    assert PANEL_SHA256 == (
        "bd95c2ab96610b492f9ebdeaa4485e918fca2c1b80c122127aa9743c5e102c81"
    )


def test_seed_matches_committed_run() -> None:
    # the 2026-08-01 forward run: series_index 4239 -> cone_seed 20264212
    assert seed_for(4239) == 20264212
