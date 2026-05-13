"""Tests for _fill_rv_from_price (the RV-from-price fallback).

UW's realized_volatility endpoint trails by several weeks for most tickers.
The price column is fully populated, so we derive 21d annualized log-return
stdev locally to fill the gap. This unblocks the VRP, RV-z, and HV-vs-IV
panels from running out of data 3 weeks before today.
"""

from __future__ import annotations

from datetime import date, timedelta

from uw_scan.reports.volatility_series import _fill_rv_from_price


def _walk(prices: list[float], start: date = date(2026, 1, 1)) -> list[dict]:
    return [
        {
            "market_date": start + timedelta(days=i),
            "price": p,
            "implied_volatility": 0.50,
            "realized_volatility": None,
        }
        for i, p in enumerate(prices)
    ]


def test_fills_recent_null_rv_from_price():
    # 25 days of a real price walk with ~1% daily moves alternating sign.
    cum = [100.0]
    for i in range(1, 25):
        cum.append(cum[-1] * (1.01 if i % 2 == 0 else 1 / 1.01))
    rows = _walk(cum)
    out = _fill_rv_from_price(rows)
    # First 20 rows have <21 returns of history → RV still null.
    assert all(r["realized_volatility"] is None for r in out[:20])
    # Rows 21..24 should have non-null derived RV ≈ stdev(0.01) * sqrt(252).
    for r in out[21:]:
        assert r["realized_volatility"] is not None
        # Sanity: 0.01 daily stdev * sqrt(252) ≈ 0.1587
        assert 0.10 < r["realized_volatility"] < 0.25


def test_does_not_overwrite_existing_rv():
    rows = _walk([100.0 + i for i in range(25)])
    rows[24]["realized_volatility"] = 0.99  # UW's authoritative value
    out = _fill_rv_from_price(rows)
    assert out[24]["realized_volatility"] == 0.99


def test_empty_input_returns_empty():
    assert _fill_rv_from_price([]) == []


def test_does_not_mutate_input():
    rows = _walk([100.0, 101.0, 102.0])
    original_ids = [id(r) for r in rows]
    out = _fill_rv_from_price(rows)
    assert [id(r) for r in rows] == original_ids
    # And the output rows are different objects from the input rows.
    assert all(id(o) != id(i) for o, i in zip(out, rows))


def test_handles_zero_or_negative_price_gracefully():
    rows = _walk([100.0, 0.0, 101.0, 102.0])  # one bogus price
    out = _fill_rv_from_price(rows)
    # No exception; missing-rv stays null on rows with bad neighbors.
    assert out[0]["realized_volatility"] is None
