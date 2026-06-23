from datetime import date, timedelta

import pytest

from uw_scan.reports.goas_putwrite_account import GoasConfig, simulate_putwrite
from uw_scan.reports.vrp_macro_harvest import _Loaded
from uw_scan.reports.vrp_structure import CostModel

ZERO_COST = CostModel(
    per_contract=0.0, slippage_frac=0.0, slippage_min=0.0, round_trip=True
)


def _flat_loaded(n_days: int, spot: float, iv: float) -> _Loaded:
    """Constructed test input (NOT market data): n consecutive days at a constant
    spot and IV."""
    d0 = date(2010, 1, 4)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    adj = [(d, spot) for d in dates]
    pidx = {d: i for i, d in enumerate(dates)}
    rows = [{"market_date": d, "iv": iv} for d in dates]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def _selloff_loaded(
    n_days: int, spot0: float, iv: float, *, drop_to: float, drop_at: int
) -> _Loaded:
    d0 = date(2010, 1, 4)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    spots = [spot0 if i < drop_at else drop_to for i in range(n_days)]
    adj = list(zip(dates, spots, strict=True))
    pidx = {d: i for i, d in enumerate(dates)}
    rows = [{"market_date": d, "iv": iv} for d in dates]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def test_flat_path_no_breach_nav_rises_by_net_credit():
    loaded = _flat_loaded(400, spot=100.0, iv=0.18)
    cfg = GoasConfig(
        short_delta=0.15,
        dte_days=30,
        cadence_days=5,
        capital=1_000_000.0,
        cost=ZERO_COST,
    )
    res = simulate_putwrite(loaded, cfg)
    assert res.trades, "expected trades on a 400-day flat path"
    # flat spot, all puts expire OTM → every trade keeps full credit, none breached
    assert all(not t.breached for t in res.trades)
    assert all(t.net_pnl > 0 for t in res.trades)
    # post-cost NAV ends above start (premium harvested); equals gross at zero cost
    assert res.equity_curve_costed[-1][1] > res.equity_curve_costed[0][1]
    assert res.equity_curve_costed[-1][1] == pytest.approx(
        res.equity_curve_gross[-1][1]
    )


def test_selloff_loss_bounded_by_defined_risk():
    # spot crashes 100 → 50; a 0.15-delta put can lose at most (strike − credit)·100·contracts
    loaded = _selloff_loaded(120, spot0=100.0, iv=0.30, drop_to=50.0, drop_at=40)
    cfg = GoasConfig(
        short_delta=0.15,
        dte_days=30,
        cadence_days=5,
        capital=1_000_000.0,
        cost=ZERO_COST,
    )
    res = simulate_putwrite(loaded, cfg)
    for t in res.trades:
        floor = -(t.strike - t.credit) * cfg.multiplier * t.contracts
        assert (
            t.net_pnl >= floor - 1e-6
        )  # never worse than the assignment-to-zero floor


def test_deterministic():
    loaded = _flat_loaded(200, spot=100.0, iv=0.18)
    cfg = GoasConfig(short_delta=0.20, dte_days=30, cost=ZERO_COST)
    a = simulate_putwrite(loaded, cfg)
    b = simulate_putwrite(loaded, cfg)
    assert [t.net_pnl for t in a.trades] == [t.net_pnl for t in b.trades]
    assert a.equity_curve_costed == b.equity_curve_costed


def test_no_entry_day_premium_frontload():
    # fair-value marking ⇒ at entry the open put marks ≈ credit, so unrealized ≈ 0
    # and NAV does NOT jump by the full premium on day 0. cadence > n_days ⇒ a single
    # entry at i=0 to isolate the behavior.
    loaded = _flat_loaded(120, spot=100.0, iv=0.18)
    cfg = GoasConfig(
        short_delta=0.15,
        dte_days=30,
        cadence_days=200,
        capital=1_000_000.0,
        cost=ZERO_COST,
    )
    res = simulate_putwrite(loaded, cfg)
    assert len(res.trades) == 1
    t = res.trades[0]
    full_credit = t.credit * cfg.multiplier * t.contracts
    nav0 = res.equity_curve_gross[0][1]
    assert abs(nav0 - cfg.capital) < 0.1 * full_credit  # no entry-day front-load
    # the full credit is realized by expiry (flat path, OTM → keeps all credit)
    assert res.equity_curve_gross[-1][1] == pytest.approx(
        cfg.capital + full_credit, rel=1e-6
    )


def test_costs_reduce_net_pnl():
    # cost path must be exercised (all other tests use ZERO_COST). Same path/strikes;
    # transaction costs strictly lower every trade's net P&L and the ending NAV.
    loaded = _flat_loaded(200, spot=100.0, iv=0.18)
    costed = CostModel(
        per_contract=0.65, slippage_frac=0.01, slippage_min=0.05, round_trip=True
    )
    res_cost = simulate_putwrite(
        loaded, GoasConfig(short_delta=0.15, dte_days=21, cost=costed)
    )
    res_free = simulate_putwrite(
        loaded, GoasConfig(short_delta=0.15, dte_days=21, cost=ZERO_COST)
    )
    assert res_cost.trades and len(res_cost.trades) == len(res_free.trades)
    for tc, tf in zip(res_cost.trades, res_free.trades, strict=True):
        assert tc.net_pnl < tf.net_pnl
    assert res_cost.equity_curve_costed[-1][1] < res_free.equity_curve_costed[-1][1]
