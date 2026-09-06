"""The ARGON-ADDED skewed-t arm: reduction to the symmetric t, bounds, determinism.

Every input here is REAL frozen SPX history — `src/uw_scan/density/data/panel.parquet`,
the same digest-pinned panel the golden parity test fits. No synthetic returns.

What this arm can and cannot move is worth stating where the tests are: the family enters
the LIKELIHOOD only. `cone.gjr_std_boot_cone` draws its innovations by block bootstrap from
the empirical standardized residual pool, so the fitted (eta, lambda) never become the
shape of a simulated path — they move omega/alpha/gamma/beta, and through them the variance
path, v_next and the residual pool itself. Nothing else.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from uw_scan.density.constants import (
    CHANNEL_BAD_SKEW,
    MAX_FAILURE_CARRY_DAYS,
    SKEWT_START_LAMBDA,
)
from uw_scan.density.fit import ARMS, ArmSpec, _guard, fit_v8

PANEL = (
    Path(__file__).resolve().parents[3]
    / "src"
    / "uw_scan"
    / "density"
    / "data"
    / "panel.parquet"
)


@pytest.fixture(scope="module")
def spx_returns() -> np.ndarray:
    closes = (
        pd.read_parquet(PANEL).sort_values("trade_date")["close"].to_numpy(dtype=float)
    )
    return closes[1:] / closes[:-1] - 1.0


def test_arm_skewt_is_arm_g_with_an_asymmetric_family() -> None:
    """Same configuration as the production arm; the innovation family is the ONLY change."""
    assert ARMS["SKEWT"] == ArmSpec("skewt", True, True, MAX_FAILURE_CARRY_DAYS)
    g = ARMS["G"]
    assert (ARMS["SKEWT"].multi_start, ARMS["SKEWT"].retry, ARMS["SKEWT"].max_carry) == (
        g.multi_start,
        g.retry,
        g.max_carry,
    )
    assert ARMS["SKEWT"].legacy is False
    assert ARMS["G"].family == "normal"  # production arm untouched


def test_skewed_likelihood_reduces_to_student_t_at_the_symmetric_value(
    spx_returns: np.ndarray,
) -> None:
    """lambda = 0 is not "approximately symmetric" — Hansen's density IS the standardized
    Student-t there, so the two log-likelihoods must agree to floating-point noise on the
    same real residuals. This is what makes the arm a strict generalisation of arm H."""
    from arch.univariate import SkewStudent, StudentsT

    resids = 100.0 * np.log1p(spx_returns[-1500:])
    sigma2 = np.full_like(resids, float(np.var(resids)))
    for eta in (4.0, 8.0, 30.0):
        sym = StudentsT().loglikelihood(
            np.array([eta]), resids, sigma2, individual=False
        )
        skew = SkewStudent().loglikelihood(
            np.array([eta, SKEWT_START_LAMBDA]), resids, sigma2, individual=False
        )
        assert float(skew) == pytest.approx(float(sym), rel=0.0, abs=1e-8)


def test_fit_returns_skew_and_df_within_bounds(spx_returns: np.ndarray) -> None:
    """The fit must produce BOTH extra parameters, admissibly: eta > 2 (the unit-variance
    standardisation) and |lambda| < 1 (Hansen's b-normalisation)."""
    params, attempts = fit_v8(spx_returns, family="skewt", multi_start=True)
    assert params is not None
    assert set(params) == {"omega", "alpha", "gamma", "beta", "eta", "lambda"}
    assert 2.0 < params["eta"] < np.inf
    assert -1.0 < params["lambda"] < 1.0
    assert len(attempts) == 5  # index 0 = arch's own default + the 4 MULTI_STARTS
    assert all(np.isfinite(a.loglik) for a in attempts)


def test_fit_is_deterministic_across_two_calls(spx_returns: np.ndarray) -> None:
    """No unseeded randomness anywhere in the estimator: same input, byte-identical output."""
    a, _ = fit_v8(spx_returns, family="skewt", multi_start=True)
    b, _ = fit_v8(spx_returns, family="skewt", multi_start=True)
    assert a == b


def test_guard_rejects_a_skew_pinned_on_the_bound() -> None:
    """|lambda| = 1 collapses the density's normalisation — rejected, never published."""
    base = {"omega": 0.04, "alpha": 0.01, "gamma": 0.24, "beta": 0.83, "eta": 7.0}
    ok, channel, _ = _guard({**base, "lambda": -0.2}, "skewt")
    assert ok and channel == "ok"
    ok, channel, _ = _guard({**base, "lambda": -1.0}, "skewt")
    assert not ok and channel == CHANNEL_BAD_SKEW


def test_unknown_family_still_raises() -> None:
    with pytest.raises(ValueError, match="family must be one of"):
        fit_v8(np.zeros(1000), family="laplace")
