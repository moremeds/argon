import math

import pytest

from uw_scan.reports.vrp_structure import (
    CostModel,
    bs_delta,
    bs_price,
    build_iron_condor,
    condor_expiry_pnl,
    strike_for_delta,
)

S, T, R, SIG = 100.0, 20 / 252, 0.04, 0.30


def test_bs_put_call_parity():
    c = bs_price(S, 100.0, T, R, SIG, is_call=True)
    p = bs_price(S, 100.0, T, R, SIG, is_call=False)
    # C - P = S - K e^{-rT}
    assert c - p == pytest.approx(S - 100.0 * math.exp(-R * T), abs=1e-9)


def test_strike_for_delta_recovers_delta():
    k_call = strike_for_delta(S, T, R, SIG, 0.16, is_call=True)
    k_put = strike_for_delta(S, T, R, SIG, 0.16, is_call=False)
    assert k_call > S > k_put  # OTM both sides
    assert bs_delta(S, k_call, T, R, SIG, is_call=True) == pytest.approx(0.16, abs=1e-3)
    assert abs(bs_delta(S, k_put, T, R, SIG, is_call=False)) == pytest.approx(
        0.16, abs=1e-3
    )


def test_iron_condor_well_formed():
    ic = build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.08)
    assert ic.long_put < ic.short_put < S < ic.short_call < ic.long_call
    assert ic.credit > 0
    assert ic.put_width > 0 and ic.call_width > 0
    # defined-risk identity: max loss = widest wing minus credit collected
    assert ic.max_loss == pytest.approx(
        max(ic.put_width, ic.call_width) - ic.credit, abs=1e-9
    )
    assert ic.credit < max(ic.put_width, ic.call_width)  # credit can't exceed width


def test_expiry_pnl_max_profit_inside_short_strikes():
    ic = build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.08)
    # settle dead center → both spreads expire worthless → keep full credit
    assert condor_expiry_pnl(ic, S) == pytest.approx(ic.credit, abs=1e-9)


def test_expiry_pnl_max_loss_below_long_put():
    ic = build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.08)
    deep = ic.long_put - 10.0  # below the long put → full put-spread loss
    pnl = condor_expiry_pnl(ic, deep)
    assert pnl == pytest.approx(ic.credit - ic.put_width, abs=1e-9)
    assert pnl < 0


def test_build_rejects_bad_inputs():
    with pytest.raises(ValueError):
        build_iron_condor(S, 0.0, T, R, short_delta=0.16, wing_delta=0.08)  # sigma<=0
    with pytest.raises(ValueError):
        build_iron_condor(S, SIG, T, R, short_delta=0.16, wing_delta=0.20)  # wing>short


def test_cost_model_positive_and_round_trip_doubles():
    legs = (1.0, 0.5, 1.0, 0.5)
    one = CostModel(0.65, 0.01, 0.05, round_trip=False)
    two = CostModel(0.65, 0.01, 0.05, round_trip=True)
    assert one.total(legs, contracts=1) > 0
    assert two.total(legs, contracts=1) == pytest.approx(
        2 * one.total(legs, 1), abs=1e-9
    )
