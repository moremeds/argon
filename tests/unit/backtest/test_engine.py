from __future__ import annotations

from datetime import date, timedelta

from uw_scan.backtest.engine import SignalPoint, walk_forward_backtest


def _series(n, start=date(2026, 1, 5)):
    return [
        SignalPoint(date=start + timedelta(days=i), signal={"i": i}) for i in range(n)
    ]


def test_entry_rule_never_sees_the_future():
    pts = _series(10)
    fwd = {p.date: 0.01 for p in pts}
    seen = []

    def rule(history, point):
        assert history[-1] is point
        assert all(h.date <= point.date for h in history)
        seen.append(len(history))
        return 1.0

    walk_forward_backtest(pts, fwd, rule)
    assert seen == list(range(1, 11))  # history strictly grows, one origin at a time


def test_forward_keying_and_costs():
    pts = _series(2)
    fwd = {pts[0].date: 0.10}  # second origin has no forward return yet
    out = walk_forward_backtest(pts, fwd, lambda h, p: -1.0, cost_fraction=0.01)
    assert out["n_trades"] == 1
    assert out["skipped_no_forward"] == 1
    t = out["trades"][0]
    assert t["gross_return"] == -0.10  # short * +10% move
    assert abs(t["net_return"] - (-0.11)) < 1e-12  # cost scales with |position|


def test_flat_position_skips_without_counting():
    pts = _series(3)
    fwd = {p.date: 0.01 for p in pts}
    out = walk_forward_backtest(pts, fwd, lambda h, p: 0.0)
    assert out["n_trades"] == 0 and out["skipped_no_forward"] == 0


def test_unsorted_input_is_sorted_defensively():
    pts = _series(5)
    fwd = {p.date: 0.01 for p in pts}
    out = walk_forward_backtest(list(reversed(pts)), fwd, lambda h, p: 1.0)
    assert [t["date"] for t in out["trades"]] == [p.date for p in pts]
