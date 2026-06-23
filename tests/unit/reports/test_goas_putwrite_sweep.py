from datetime import date, timedelta

import pytest

from uw_scan.reports.goas_putwrite_sweep import (
    DELTAS,
    DTES,
    FEE_GRID,
    RANK_FEE,
    apply_fee_to_curve,
    run_sweep,
    slice_curve,
)
from uw_scan.reports.vrp_macro_harvest import _Loaded


def _flat_loaded(n_days: int, spot: float, iv: float) -> _Loaded:
    d0 = date(2007, 1, 3)
    dates = [d0 + timedelta(days=i) for i in range(n_days)]
    adj = [(d, spot) for d in dates]
    pidx = {d: i for i, d in enumerate(dates)}
    rows = [{"market_date": d, "iv": iv} for d in dates]
    return _Loaded(adj=adj, pidx=pidx, rows=rows, events=[])


def test_grids_are_specified():
    assert DELTAS == (0.05, 0.10, 0.15, 0.20, 0.25, 0.30)
    assert DTES == (21, 30, 42, 63)
    assert FEE_GRID == (0.0, 0.005, 0.010, 0.015)
    assert RANK_FEE in FEE_GRID  # ranking fee basis must be a swept level


def test_apply_fee_monotone():
    curve = [(date(2010, 1, 1) + timedelta(days=i), 100.0) for i in range(252)]
    base = apply_fee_to_curve(curve, 0.0)
    fee1 = apply_fee_to_curve(curve, 0.01)
    assert base[-1][1] == pytest.approx(100.0)
    assert fee1[0][1] == pytest.approx(100.0)  # no fee charged on the seed day
    assert fee1[-1][1] < base[-1][1]


def test_slice_curve_bounds():
    curve = [(date(2010, 1, 1) + timedelta(days=i), float(i)) for i in range(100)]
    sub = slice_curve(curve, date(2010, 1, 10), date(2010, 1, 20))
    assert sub[0][0] >= date(2010, 1, 10) and sub[-1][0] <= date(2010, 1, 20)


def test_run_sweep_covers_full_grid():
    loaded = _flat_loaded(500, spot=100.0, iv=0.18)
    out = run_sweep(loaded, skew=None)
    # one cell per (delta, dte) for this pricing mode (flat, since skew=None)
    assert len(out["cells"]) == len(DELTAS) * len(DTES)
    assert "benchmark" in out and "ranking" in out
    assert all("costed" in c and "gross" in c and "regimes" in c for c in out["cells"])
    assert all("calm" in c["regimes"] for c in out["cells"])
