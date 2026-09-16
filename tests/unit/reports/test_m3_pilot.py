from datetime import date
from types import SimpleNamespace

from scripts.research.vrp.m3_pilot import _settings_for_cost, settlement_metrics
from uw_scan.reports.vrp_capital_account import _cost_model


def test_initial_peak_drawdown_and_cost_ordering():
    rungs = [
        SimpleNamespace(
            entry_date=date(2020, 1, 1),
            exit_date=date(2020, 2, 1),
            net_pnl=-100.0,
            contracts=1,
        ),
        SimpleNamespace(
            entry_date=date(2020, 2, 2),
            exit_date=date(2020, 3, 1),
            net_pnl=50.0,
            contracts=1,
        ),
    ]
    metrics, path = settlement_metrics(rungs, capital=1_000.0)
    assert metrics["max_drawdown"] == 0.10
    assert path[0]["equity_usd"] == 1_000.0

    modeled = [
        _cost_model(_settings_for_cost(cost)).total((10.0, 5.0), 1)
        for cost in (0.0, 2.0, 5.0)
    ]
    assert modeled == [0.0, 2.0, 5.0]
    assert [100.0 - cost for cost in modeled] == [100.0, 98.0, 95.0]
