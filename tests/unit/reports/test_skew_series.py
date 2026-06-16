"""O(n) skew series helpers match the per-point card functions on dense data.

Guards the M3 perf rewrite: _history_points / _rho_points replaced O(n^2) per-point
Series/DataFrame rebuilds with vectorised rolling, and must preserve the values.
"""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.cards.skew_first_principles import (
    compute_skew_baseline,
    compute_spot_vol_rho,
)
from uw_scan.reports.skew_analytics import _history_points, _rho_points

_TOL = 1e-6  # rolling vs two-pass accumulation differ at FP noise level


def _rr_hist(n: int = 210) -> list[dict]:
    base = date(2026, 1, 1)
    return [
        {
            "market_date": base + timedelta(days=i),
            "risk_reversal": 0.001 + 0.0001 * (i % 7) + (0.05 if i == n - 1 else 0.0),
        }
        for i in range(n)
    ]


def _rv(n: int = 210) -> list[dict]:
    base = date(2026, 1, 1)
    out = []
    p, iv = 100.0, 0.20
    for i in range(n):
        p *= 0.999 if i % 2 == 0 else 1.0008
        iv += 0.0003 if i % 3 == 0 else -0.0001
        out.append(
            {
                "market_date": base + timedelta(days=i),
                "price": p,
                "implied_volatility": iv,
            }
        )
    return out


def test_history_points_match_baseline():
    rr = _rr_hist()
    floats = [r["risk_reversal"] for r in rr]
    hist = _history_points(rr)
    assert len(hist) == len(rr)
    for k in (0, 28, 29, 100, len(rr) - 1):
        b = compute_skew_baseline(floats[: k + 1])
        if b["z"] is None:
            assert hist[k].z is None
        else:
            assert abs(float(hist[k].z) - b["z"]) < _TOL
        if b["pct"] is None:
            assert hist[k].pct is None
        else:
            assert abs(float(hist[k].pct) - b["pct"]) < _TOL


def test_rho_points_match_compute():
    rv = _rv()
    pts = {p.date: p for p in _rho_points(rv, window=63)}
    for k in (63, 120, len(rv) - 1):
        expected = compute_spot_vol_rho(rv[: k + 1], window=63)
        d = rv[k]["market_date"]
        if expected is None:
            assert d not in pts
        else:
            assert d in pts
            assert abs(float(pts[d].rho) - expected) < _TOL


def test_history_points_empty():
    assert _history_points([]) == []
    assert (
        _history_points([{"market_date": date(2026, 1, 1), "risk_reversal": None}])
        == []
    )


def test_rho_points_short_series_empty():
    assert _rho_points(_rv(10), window=63) == []
