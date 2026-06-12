"""Pure splice/carry-forward primitives for the regime live compute."""

from __future__ import annotations

from datetime import date, datetime, timezone

from uw_scan.scanners.live_quotes import (
    LiveQuote,
    carry_forward,
    live_session_date,
    splice_session_value,
)


def _q(symbol: str, price: float, iso: str) -> LiveQuote:
    return LiveQuote(
        symbol=symbol,
        price=price,
        quoted_at=datetime.fromisoformat(iso).astimezone(timezone.utc),
        source="xenon_ws",
    )


def test_live_session_date_is_et_date_of_freshest_quote():
    quotes = {
        # 2026-06-12 01:30 UTC == 2026-06-11 21:30 ET → ET date is the 11th
        "VIX": _q("VIX", 22.2, "2026-06-12T01:30:00+00:00"),
        "HYG": _q("HYG", 79.7, "2026-06-11T19:55:00+00:00"),
    }
    assert live_session_date(quotes) == date(2026, 6, 11)


def test_live_session_date_empty():
    assert live_session_date({}) is None


def test_splice_appends_today():
    series = {date(2026, 6, 10): 20.0, date(2026, 6, 11): 21.0}
    out = splice_session_value(series, 22.2, date(2026, 6, 12))
    assert out[date(2026, 6, 12)] == 22.2
    assert series == {date(2026, 6, 10): 20.0, date(2026, 6, 11): 21.0}  # no mutation


def test_splice_replaces_existing_close():
    series = {date(2026, 6, 11): 21.0}
    out = splice_session_value(series, 22.2, date(2026, 6, 11))
    assert out[date(2026, 6, 11)] == 22.2


def test_carry_forward_fills_missing_session():
    series = {date(2026, 6, 10): 17.5, date(2026, 6, 11): 17.8}
    out, carried = carry_forward(series, date(2026, 6, 12))
    assert carried is True
    assert out[date(2026, 6, 12)] == 17.8


def test_carry_forward_noop_when_present_or_empty():
    series = {date(2026, 6, 12): 17.8}
    out, carried = carry_forward(series, date(2026, 6, 12))
    assert carried is False and out == series
    out2, carried2 = carry_forward({}, date(2026, 6, 12))
    assert carried2 is False and out2 == {}
