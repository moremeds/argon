import math
from datetime import date, timedelta
from types import SimpleNamespace

from uw_scan.reports.vrp_capital_account import CapitalConfig
from uw_scan.reports.vrp_macro_drawdown import _Loaded
from uw_scan.reports.vrp_robustness import (
    _pct,
    bear_start_study,
    buy_and_hold,
    equity_curve_metrics,
    mc_block_bootstrap,
    mc_config_perturb,
    mc_entry_jitter,
    mc_random_start,
    min_viable_capital,
    monthly_equity,
    weekday_sweep,
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


def test_weekday_sweep_has_six_rows():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=300)
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    rows = weekday_sweep(ld, _settings(), cfg, 0.04)
    labels = {r["entry_weekday"] for r in rows}
    assert labels == {0, 1, 2, 3, 4, "stride"}


def test_bear_start_study_returns_summary_and_path():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=400, start=date(2015, 1, 1))
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    summary, path = bear_start_study(
        ld, _settings(), cfg, 0.04, starts=(date(2015, 6, 1),), windows_months=(6, 12)
    )
    assert len(summary) == 1
    r = summary[0]
    assert "ret_6m" in r and "maxdd_6m_pct" in r and "ret_12m" in r
    assert r["start"] == date(2015, 6, 1)
    # long-form path drives the full-lived-experience chart
    assert path and path[0]["start"] == date(2015, 6, 1)
    assert {"start", "year", "month", "equity", "drawdown_pct"} <= set(path[0])


def test_mc_entry_jitter_deterministic_and_shaped():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=400)
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    a = mc_entry_jitter(ld, _settings(), cfg, 0.04, n_trials=20, jitter=2, seed=11)
    b = mc_entry_jitter(ld, _settings(), cfg, 0.04, n_trials=20, jitter=2, seed=11)
    assert a == b
    assert a["n_trials"] == 20 and "p5" in a and "p95" in a and a["seed"] == 11


def test_mc_block_bootstrap_ci_ordered():
    vals = [0.02, -0.01, 0.03, 0.00, 0.015, -0.02, 0.025, 0.01] * 12
    out = mc_block_bootstrap(vals, n_trials=500, mean_block=6.0, seed=3)
    assert out["p5"] <= out["median"] <= out["p95"]


def test_mc_random_start_deterministic():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=600)
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    a = mc_random_start(ld, _settings(), cfg, 0.04, n_trials=15, seed=5)
    b = mc_random_start(ld, _settings(), cfg, 0.04, n_trials=15, seed=5)
    assert a == b


def test_mc_random_start_window_bounds_sampled_starts():
    # the bear-extension (#5): every sampled start must fall inside [min_start, max_start]
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=600)  # 2020-01 .. ~2022-04
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    lo, hi = date(2020, 6, 1), date(2021, 1, 1)
    w = mc_random_start(
        ld,
        _settings(),
        cfg,
        0.04,
        n_trials=10,
        seed=5,
        min_start=lo,
        max_start=hi,
        min_tail_months=6,
    )
    assert w == mc_random_start(
        ld,
        _settings(),
        cfg,
        0.04,
        n_trials=10,
        seed=5,
        min_start=lo,
        max_start=hi,
        min_tail_months=6,
    )
    assert w["trials"]
    assert all(
        lo <= date.fromisoformat(t["param"].split("=", 1)[1]) <= hi for t in w["trials"]
    )


def test_mc_config_perturb_deterministic():
    ld = _spx_loaded(spot=5000.0, iv=0.20, z=1.0, n=400)
    cfg = CapitalConfig(
        capital=1_000_000_000.0,
        base_risk_pct=0.05,
        overlay_mult=0.0,
        rich_threshold=99.0,
        names=("SPX",),
    )
    a = mc_config_perturb(ld, _settings(), cfg, 0.04, n_trials=15, seed=9)
    b = mc_config_perturb(ld, _settings(), cfg, 0.04, n_trials=15, seed=9)
    assert a == b
