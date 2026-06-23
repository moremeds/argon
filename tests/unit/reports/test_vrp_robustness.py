import math
from datetime import date, timedelta
from types import SimpleNamespace

from uw_scan.reports.vrp_macro_drawdown import _Loaded
from uw_scan.reports.vrp_robustness import (
    _pct,
    buy_and_hold,
    equity_curve_metrics,
    min_viable_capital,
    monthly_equity,
)


def _settings():
    return SimpleNamespace(
        vrp_risk_free_rate=0.04,
        vrp_cost_per_contract=0.65,
        vrp_slippage_frac=0.01,
        vrp_slippage_min=0.05,
        vrp_cost_round_trip=True,
    )


def _spx_loaded(*, spot=5000.0, iv=0.20, z=1.0, n=120, start=date(2020, 1, 1)):
    dates, d = [], start
    while len(dates) < n:
        if d.weekday() < 5:
            dates.append(d)
        d += timedelta(days=1)
    adj = [(dd, spot) for dd in dates]
    rows = [
        {"market_date": dd, "iv": iv, "rv": iv - 0.05, "vrp": 0.05, "vrp_z_20": z}
        for dd in dates
    ]
    return _Loaded(
        adj=adj, pidx={dd: i for i, dd in enumerate(dates)}, rows=rows, events=[]
    )


def test_min_viable_capital_floor_scales_inverse_to_risk_pct():
    ld = _spx_loaded(spot=5000.0, iv=0.20)
    out = min_viable_capital(ld, _settings(), hold=30)
    assert out["first_mlpc"] > 0
    # floor at 100% risk == one spread's max loss; at 50% risk it doubles
    assert out["c0_floor"][1.0] <= out["c0_floor"][0.5]
    assert out["c0_floor"][1.0] >= out["first_mlpc"]


def test_buy_and_hold_doubling_is_100pct_return():
    adj = [(date(2020, 1, 1), 100.0), (date(2021, 1, 1), 200.0)]
    out = buy_and_hold(adj, 50_000.0, 0.04)
    assert math.isclose(out["maxdd_dollars"], 0.0, abs_tol=1.0)  # monotonic up
    assert out["cagr"] > 0.0


def test_monthly_equity_starts_above_capital_on_gains():
    res = SimpleNamespace(monthly_excess={(2020, 1): 0.10, (2020, 2): 0.05})
    eq = monthly_equity(res, 50_000.0)
    assert eq[0] == ((2020, 1), 55_000.0)
    assert eq[-1] == ((2020, 2), 57_500.0)


def test_equity_curve_metrics_geometric_return():
    pts = [((2020, 1), 55_000.0), ((2020, 2), 60_500.0)]  # +10% then +10%
    m = equity_curve_metrics(pts, 50_000.0, 0.04)
    assert m["maxdd_dollars"] == 0.0
    assert m["cagr"] > 0.0


def test_pct_basic():
    assert _pct([1, 2, 3, 4, 5], 0.5) == 3
