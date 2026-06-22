"""Bull put spread + cash-secured put: pricing, capped/uncapped loss, breach."""

from uw_scan.reports.vrp_structure import (
    CostModel,
    build_bull_put_spread,
    build_cash_secured_put,
)

T = 20 / 252  # ~one month
COST = CostModel(0.65, 0.01, 0.05, round_trip=True)


def test_bull_put_spread_collects_credit_and_caps_loss():
    s = build_bull_put_spread(100.0, 0.25, T, 0.04, short_delta=0.16, wing_delta=0.08)
    assert s.short_put > s.long_put  # sell higher strike, buy lower wing
    assert s.credit > 0 and 0 < s.max_loss
    # settle above the short strike → keep the full credit, not breached
    assert s.expiry_pnl(100.0) == s.credit
    assert not s.breached(100.0)
    # settle below the long wing → loss capped at exactly max_loss, breached
    assert s.expiry_pnl(s.long_put - 50) == -s.max_loss
    assert s.breached(s.long_put - 50)


def test_csp_collects_more_credit_but_loss_runs_to_strike():
    csp = build_cash_secured_put(100.0, 0.25, T, 0.04, short_delta=0.16)
    spread = build_bull_put_spread(
        100.0, 0.25, T, 0.04, short_delta=0.16, wing_delta=0.08
    )
    # no long wing to pay for → CSP collects more premium than the spread
    assert csp.credit > spread.credit
    # but the risk is the whole strike (assignment to zero), not the wing width
    assert csp.max_loss == csp.short_put - csp.credit
    assert csp.max_loss > spread.max_loss
    assert csp.expiry_pnl(100.0) == csp.credit  # above strike → keep credit
    assert csp.expiry_pnl(0.0) == csp.credit - csp.short_put  # = -max_loss
    assert csp.breached(csp.short_put - 1) and not csp.breached(csp.short_put + 1)


def test_cost_scales_to_leg_count():
    # 2-leg spread costs less than a 4-leg condor's per-leg commission would imply.
    two_leg = COST.total((1.2, 0.4), contracts=1)
    one_leg = COST.total((1.2,), contracts=1)
    four_leg = COST.total((1.2, 0.4, 1.1, 0.3), contracts=1)
    assert one_leg < two_leg < four_leg
