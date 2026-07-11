"""Unit tests for the technical_live massive cross-check helpers (pure, no DB)."""

from __future__ import annotations

from datetime import date as _date
from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

from uw_scan.worker.jobs.technical_live import (
    _due_for_massive,
    _massive_today_ohlc,
)

_NOW = datetime(2026, 7, 10, 16, 0, tzinfo=timezone.utc)


def test_due_for_massive_no_prior_check():
    assert _due_for_massive(None, _NOW) is True
    assert _due_for_massive({}, _NOW) is True


def test_due_for_massive_within_interval_is_false():
    prior = {"checked_at": (_NOW - timedelta(minutes=5)).isoformat()}
    assert _due_for_massive(prior, _NOW) is False


def test_due_for_massive_after_interval_is_true():
    prior = {"checked_at": (_NOW - timedelta(minutes=16)).isoformat()}
    assert _due_for_massive(prior, _NOW) is True


def test_due_for_massive_unparseable_timestamp_is_true():
    assert _due_for_massive({"checked_at": "garbage"}, _NOW) is True


class _FakeProvider:
    def __init__(self, bars):
        self._bars = bars

    def fetch_daily(self, ticker, start, end):
        return self._bars


def test_massive_today_ohlc_picks_the_session_bar():
    d = _date(2026, 7, 10)
    bars = [
        SimpleNamespace(date=_date(2026, 7, 9), open=1, high=2, low=0.5, close=1.5),
        SimpleNamespace(date=d, open=10, high=12, low=9, close=11),
    ]
    assert _massive_today_ohlc(_FakeProvider(bars), "TSLA", d) == {
        "open": 10.0,
        "high": 12.0,
        "low": 9.0,
        "close": 11.0,
    }


def test_massive_today_ohlc_empty_is_none():
    assert _massive_today_ohlc(_FakeProvider([]), "TSLA", _date(2026, 7, 10)) is None


def test_massive_today_ohlc_never_raises():
    class _Boom:
        def fetch_daily(self, *_a):
            raise RuntimeError("massive down")

    assert _massive_today_ohlc(_Boom(), "TSLA", _date(2026, 7, 10)) is None
