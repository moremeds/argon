"""A window-bounded load must reproduce the full load's latest row exactly
(rv, vrp, z) and be bounded relative to the caller's `since`, not today."""

from __future__ import annotations

import math
from datetime import date, timedelta

from uw_scan.reports import vrp_macro_drawdown as mod

D0 = date(2020, 1, 1)


def _series(n: int) -> tuple[dict, dict]:
    spot, vol = {}, {}
    px = 3000.0
    for i in range(n):
        d = D0 + timedelta(days=i)
        if d.weekday() >= 5:
            continue
        px *= 1.0 + 0.01 * math.sin(i / 7.0)
        spot[d] = px
        vol[d] = 15.0 + 8.0 * abs(math.sin(i / 11.0))
    return spot, vol


class _Repo:
    """Serves vol_index_daily rows for SPX/VIX from an in-memory series,
    honouring the `trade_date >= %s` bound the real query applies."""

    def __init__(self, spot, vol):
        self._by_symbol = {"SPX": spot, "VIX": vol}
        self.reads: list[tuple[str, date]] = []

        repo = self

        class _Cur:
            def __init__(self):
                self._rows = []

            def execute(self, _sql, params):
                symbol, start = params
                repo.reads.append((symbol, start))
                src = repo._by_symbol[symbol]
                self._rows = [(d, c) for d, c in sorted(src.items()) if d >= start]

            def fetchall(self):
                return self._rows

            def __enter__(self):
                return self

            def __exit__(self, *_a):
                return False

        class _Conn:
            def cursor(self):
                return _Cur()

        self.conn = _Conn()


def test_bounded_load_matches_full_load_latest_row_and_bounds_reads():
    spot, vol = _series(1500)
    repo = _Repo(spot, vol)
    full = mod.load_index_vol(repo, "SPX")
    as_of = max(spot)
    since = as_of - timedelta(days=mod.SIGNAL_LOOKBACK_DAYS)
    bounded = mod.load_index_vol(repo, "SPX", since=since)

    assert bounded.rows[-1] == full.rows[-1]
    assert bounded.rows[-1]["vrp_z_20"] is not None
    assert len(bounded.rows) < len(full.rows)
    assert all(start >= since for _s, start in repo.reads[2:])


def test_since_before_spec_start_is_clamped_to_spec_start():
    spot, vol = _series(400)
    repo = _Repo(spot, vol)
    mod.load_index_vol(repo, "SPX", since=date(1990, 1, 1))
    spec_start = mod.INDEX_SPECS["SPX"]["start"]
    assert all(start == spec_start for _s, start in repo.reads)
