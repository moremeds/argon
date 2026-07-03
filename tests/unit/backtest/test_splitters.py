from __future__ import annotations

from datetime import date

from uw_scan.backtest.splitters import time_ordered_holdout


def _obs(n: int) -> list[dict]:
    return [{"market_date": date(2026, 1, 1 + i % 27), "i": i} for i in range(n)]


def test_cut_boundary_matches_legacy_int_round():
    items = [{"market_date": date(2026, 1, d)} for d in range(1, 31)]  # n=30
    ordered, holdout = time_ordered_holdout(
        items, key=lambda o: o["market_date"], frac=0.40
    )
    assert len(ordered) == 30 and len(holdout) == 12  # cut = int(round(18.0)) = 18

    items5 = [{"market_date": date(2026, 1, d)} for d in range(1, 6)]  # n=5
    _, hold5 = time_ordered_holdout(items5, key=lambda o: o["market_date"], frac=0.40)
    assert len(hold5) == 2  # cut = int(round(3.0)) = 3


def test_sorts_by_key_ascending():
    items = [{"market_date": date(2026, 1, d)} for d in (5, 1, 3)]
    ordered, holdout = time_ordered_holdout(
        items, key=lambda o: o["market_date"], frac=0.40
    )
    assert [o["market_date"].day for o in ordered] == [1, 3, 5]
    assert [o["market_date"].day for o in holdout] == [5]  # cut = int(round(1.8)) = 2


def test_empty():
    assert time_ordered_holdout([], key=lambda o: o, frac=0.40) == ([], [])
