"""Arithmetic verification vectors for the anchored-VWAP deriver (hand-computed
cumulative sums, repo test convention — not market observations)."""

from datetime import date

import pytest

from uw_scan.cards.technicals import anchored_vwap


def test_cumulative_math_and_null_volume_carry():
    rows = [
        {
            "as_of": date(2026, 7, 6),
            "high": 10.0,
            "low": 8.0,
            "close": 9.0,
            "volume": 100,
        },
        {
            "as_of": date(2026, 7, 7),
            "high": 12.0,
            "low": 10.0,
            "close": 11.0,
            "volume": 300,
        },
        {
            "as_of": date(2026, 7, 8),
            "high": 13.0,
            "low": 11.0,
            "close": 12.0,
            "volume": None,
        },
    ]
    pts = anchored_vwap(rows, date(2026, 7, 6))
    assert [p["as_of"] for p in pts] == [
        date(2026, 7, 6),
        date(2026, 7, 7),
        date(2026, 7, 8),
    ]
    assert pts[0]["vwap"] == pytest.approx(9.0)  # tp=(10+8+9)/3=9
    assert pts[1]["vwap"] == pytest.approx(10.5)  # (9*100 + 11*300) / 400
    assert pts[2]["vwap"] == pytest.approx(10.5)  # null volume carries prior forward


def test_anchor_excludes_earlier_bars_and_skips_no_volume_head():
    rows = [
        {
            "as_of": date(2026, 7, 3),
            "high": 9.0,
            "low": 7.0,
            "close": 8.0,
            "volume": 500,
        },
        {
            "as_of": date(2026, 7, 6),
            "high": None,
            "low": None,
            "close": 9.0,
            "volume": None,
        },
        {
            "as_of": date(2026, 7, 7),
            "high": 12.0,
            "low": 10.0,
            "close": 11.0,
            "volume": 300,
        },
    ]
    pts = anchored_vwap(rows, date(2026, 7, 6))
    # bar before the anchor contributes nothing; anchor bar has no volume ->
    # no VWAP until the first volume-bearing bar
    assert [p["as_of"] for p in pts] == [date(2026, 7, 7)]
    assert pts[0]["vwap"] == pytest.approx(11.0)


def test_empty_and_out_of_range_anchor():
    assert anchored_vwap([], date(2026, 7, 6)) == []
    rows = [
        {
            "as_of": date(2026, 7, 6),
            "high": 10.0,
            "low": 8.0,
            "close": 9.0,
            "volume": 100,
        }
    ]
    assert anchored_vwap(rows, date(2026, 7, 7)) == []
