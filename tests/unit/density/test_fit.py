"""Estimator selection semantics — pin the tie-break and the arm registry."""

from uw_scan.density.constants import (
    CHANNEL_NOT_CONVERGED,
    CHANNEL_OK,
    MAX_FAILURE_CARRY_DAYS,
)
from uw_scan.density.fit import ARMS, ArmSpec, Attempt, select_attempt


def _ok(grid_index: int, loglik: float) -> Attempt:
    return Attempt(
        grid_index=grid_index,
        admissible=True,
        channel=CHANNEL_OK,
        loglik=loglik,
        persistence=0.966,
        converged=True,
        params={"omega": 0.04, "alpha": 0.01, "gamma": 0.24, "beta": 0.83},
    )


def test_arm_g_is_the_v13_candidate() -> None:
    assert ARMS["G"] == ArmSpec("normal", True, True, MAX_FAILURE_CARRY_DAYS)
    assert ARMS["G"].legacy is False


def test_select_attempt_ties_break_to_lowest_grid_index() -> None:
    # equal loglik within LOGLIK_TOL -> the LOWER grid index wins
    picked = select_attempt([_ok(3, -100.0), _ok(1, -100.0), _ok(2, -100.0 - 1e-9)])
    assert picked is not None
    assert picked.grid_index == 1


def test_select_attempt_prefers_higher_loglik_outside_tol() -> None:
    picked = select_attempt([_ok(0, -105.0), _ok(4, -100.0)])
    assert picked is not None
    assert picked.grid_index == 4


def test_select_attempt_none_when_nothing_admissible() -> None:
    bad = Attempt(
        grid_index=0,
        admissible=False,
        channel=CHANNEL_NOT_CONVERGED,
        loglik=float("nan"),
        persistence=float("nan"),
        converged=False,
        params=None,
    )
    assert select_attempt([bad]) is None
