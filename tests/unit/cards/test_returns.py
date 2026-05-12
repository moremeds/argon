"""1d / 1w / 30d returns from OHLC history + optional intraday price."""

from __future__ import annotations

from datetime import date, timedelta
from decimal import Decimal

from uw_scan.cards.returns import compute_returns
from uw_scan.sources.ohlc import OhlcBar


def _bar(d: date, close: str) -> OhlcBar:
    return OhlcBar(
        ticker="X",
        date=d,
        open=None,
        high=None,
        low=None,
        close=Decimal(close),
        volume=None,
    )


def test_returns_with_full_history():
    today = date(2026, 5, 8)
    history = [_bar(today - timedelta(days=22 - i), str(100 + i)) for i in range(22)]
    price = Decimal("125.00")
    r = compute_returns(history, price)
    assert r.ret_1d == (price - Decimal("121")) / Decimal("121")
    assert r.ret_1w == (price - Decimal("117")) / Decimal("117")
    assert r.ret_30d == (price - Decimal("101")) / Decimal("101")


def test_returns_insufficient_history_yields_none():
    today = date(2026, 5, 8)
    history = [
        _bar(today - timedelta(days=3), "100"),
        _bar(today - timedelta(days=2), "101"),
    ]
    r = compute_returns(history, Decimal("102"))
    assert r.ret_1d is not None
    assert r.ret_1w is None
    assert r.ret_30d is None


def test_returns_empty_history_all_none():
    r = compute_returns([], Decimal("100"))
    assert r.ret_1d is None
    assert r.ret_1w is None
    assert r.ret_30d is None


def test_returns_no_intraday_falls_back_to_last_close():
    today = date(2026, 5, 8)
    history = [_bar(today - timedelta(days=22 - i), str(100 + i)) for i in range(22)]
    r = compute_returns(history, None)
    # numerator = close[-1] = 121, ref = close[-2] = 120
    assert r.ret_1d == (Decimal("121") - Decimal("120")) / Decimal("120")
