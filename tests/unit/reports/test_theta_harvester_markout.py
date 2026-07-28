"""Forward re-marking of Theta Harvester strangles. Pure compute, no DB."""

import pytest
from uw_scan.reports.theta_harvester_markout import (
    HORIZONS,
    MAX_SNAP_DAYS,
    TERMINAL_HORIZON,
    mark_position,
)

# Frozen real IWM legs, session 2026-07-24, expiry 2026-08-21 — the same
# capture the Task 3/4 fixtures use. See tests/unit/scanners/test_theta_harvester.py
# for the source query.
_SPOT = 291.44
_PUT_K, _CALL_K = 272.0, 306.0
_PUT_IV, _CALL_IV = 0.251489543772415, 0.172509740706994


def test_horizons_cover_the_designed_taper():
    assert HORIZONS == (5, 10, 20, 30)


def test_terminal_horizon_is_a_distinct_sentinel():
    # A short strangle's loss distribution lives at expiry. Without a terminal
    # row every intermediate horizon still carries time value and the P&L
    # series is truncated above — it structurally cannot show the loss.
    assert TERMINAL_HORIZON == -1
    assert TERMINAL_HORIZON not in HORIZONS
    assert MAX_SNAP_DAYS == 7


def test_position_value_is_the_sum_of_both_leg_marks():
    put, call, value = mark_position(
        spot=_SPOT,
        put_strike=_PUT_K,
        call_strike=_CALL_K,
        put_iv=_PUT_IV,
        call_iv=_CALL_IV,
        dte_remaining=18,
        r=0.045,
    )
    assert value == pytest.approx(put + call)
    assert put > 0 and call > 0


def test_decay_shrinks_the_position_value_all_else_equal():
    # Short strangle held to fewer remaining days at an unchanged spot and vol
    # is worth less to buy back — that is the theta the strategy harvests.
    _, _, far = mark_position(
        spot=_SPOT,
        put_strike=_PUT_K,
        call_strike=_CALL_K,
        put_iv=_PUT_IV,
        call_iv=_CALL_IV,
        dte_remaining=28,
        r=0.045,
    )
    _, _, near = mark_position(
        spot=_SPOT,
        put_strike=_PUT_K,
        call_strike=_CALL_K,
        put_iv=_PUT_IV,
        call_iv=_CALL_IV,
        dte_remaining=5,
        r=0.045,
    )
    assert near < far


def test_at_expiry_the_position_is_worth_pure_intrinsic():
    # Spot 316 is 10 above the 306 call strike: intrinsic is exactly 10, and
    # the 272 put expires worthless.
    put, call, value = mark_position(
        spot=316.0,
        put_strike=_PUT_K,
        call_strike=_CALL_K,
        put_iv=_PUT_IV,
        call_iv=_CALL_IV,
        dte_remaining=0,
        r=0.045,
    )
    assert put == pytest.approx(0.0)
    assert call == pytest.approx(10.0)
    assert value == pytest.approx(10.0)


def test_vol_expansion_raises_the_cost_to_close():
    _, _, calm = mark_position(
        spot=_SPOT,
        put_strike=_PUT_K,
        call_strike=_CALL_K,
        put_iv=_PUT_IV,
        call_iv=_CALL_IV,
        dte_remaining=18,
        r=0.045,
    )
    _, _, panic = mark_position(
        spot=_SPOT,
        put_strike=_PUT_K,
        call_strike=_CALL_K,
        put_iv=_PUT_IV * 2,
        call_iv=_CALL_IV * 2,
        dte_remaining=18,
        r=0.045,
    )
    assert panic > calm
