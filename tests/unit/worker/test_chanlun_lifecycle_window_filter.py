"""Unit test for `_filter_to_session_window` in
worker/jobs/chanlun_lifecycle.py — the job/probe 30m-window drift fix.

apex's `start` param is a UTC-instant filter (a `date` -> UTC midnight), but
the walk-forward probe (scripts/research/chanlun_sublevel_probe.py) windows
30m bars by ET session date (`session_et_date`). A bar at 00:30 UTC on
`anchor_start`'s calendar date is 20:30 ET the PREVIOUS evening (EDT,
UTC-4) -- its ET session precedes `anchor_start`, but apex's raw UTC-date
`start` filter admits it anyway because the UTC date already matches. This
is a pure function with no DB/network seam, so it's unit-tested directly
rather than through the job's public integration seam (the golden-AAPL job
integration fixture returns zero 30m bars, so it can't observe this
filter's effect on S1 confirmation without fabricating a full synthetic
30m bar series)."""

from __future__ import annotations

from datetime import date

from uw_scan.worker.jobs.chanlun_lifecycle import _filter_to_session_window


def test_filter_drops_prior_session_post_market_bar_leaking_into_utc_date_head():
    anchor_start = date(2026, 7, 10)
    # 2026-07-10T00:30:00+00:00 is 2026-07-09T20:30:00-04:00 (EDT) --
    # ET session 2026-07-09, one day before anchor_start, but its UTC
    # calendar date already rolled onto 2026-07-10.
    leaking_bar = {
        "time": "2026-07-10T00:30:00+00:00",
        "high": 101.0,
        "low": 99.0,
        "close": 100.0,
    }
    # A bar genuinely inside the anchor_start ET session (09:30 ET open).
    in_window_bar = {
        "time": "2026-07-10T13:30:00+00:00",
        "high": 102.0,
        "low": 100.0,
        "close": 101.0,
    }
    result = _filter_to_session_window([leaking_bar, in_window_bar], anchor_start)
    assert result == [in_window_bar]


def test_filter_keeps_bars_from_later_sessions():
    anchor_start = date(2026, 7, 10)
    later_bar = {
        "time": "2026-07-13T13:30:00+00:00",
        "high": 103.0,
        "low": 101.0,
        "close": 102.0,
    }
    result = _filter_to_session_window([later_bar], anchor_start)
    assert result == [later_bar]


def test_filter_is_noop_on_empty_input():
    assert _filter_to_session_window([], date(2026, 7, 10)) == []
