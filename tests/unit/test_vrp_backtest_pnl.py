from uw_scan.reports.vrp_backtest import single_trade_pnl
from uw_scan.reports.vrp_structure import CostModel, build_iron_condor

COST = CostModel(0.65, 0.01, 0.05, round_trip=True)


def test_quiet_settlement_is_profit():
    ic = build_iron_condor(
        100.0, 0.30, 20 / 252, 0.04, short_delta=0.16, wing_delta=0.08
    )
    net, ror, breached = single_trade_pnl(ic, S_T=100.0, cost=COST, contracts=1)
    assert net > 0 and not breached and ror > 0


def test_tail_settlement_caps_at_defined_risk():
    ic = build_iron_condor(
        100.0, 0.30, 20 / 252, 0.04, short_delta=0.16, wing_delta=0.08
    )
    net, ror, breached = single_trade_pnl(
        ic, S_T=ic.long_put - 20, cost=COST, contracts=1
    )
    # loss bounded by max_loss × 100 + costs; never worse than that
    assert net < 0 and breached
    assert net >= -(ic.max_loss * 100) - COST.total(ic.leg_premiums, 1) - 1e-6
