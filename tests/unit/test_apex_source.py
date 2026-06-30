"""Apex/xenon bar-parse + the timestamp-join invariant the spot backfill relies on."""

from __future__ import annotations

from datetime import datetime, timezone

from uw_scan.sources.apex import _parse_bars, _parse_xenon_bars


def test_parse_bars_keys_by_utc_instant():
    closes = _parse_bars(
        [
            {"time": "2026-06-26T13:30:00+00:00", "close": 727.86},
            {"time": "2026-06-26T13:35:00+00:00", "close": "728.13"},  # str close
            {"time": "2026-06-26T13:40:00+00:00"},  # missing close → skipped
            {"close": 1.0},  # missing time → skipped
        ]
    )
    assert len(closes) == 2
    assert closes[datetime(2026, 6, 26, 13, 30, tzinfo=timezone.utc)] == 727.86
    assert closes[datetime(2026, 6, 26, 13, 35, tzinfo=timezone.utc)] == 728.13


def test_parse_xenon_bars_keys_by_utc_instant():
    """Xenon bars come back with full ISO timestamps (after the _bar_date_to_iso fix)."""
    closes = _parse_xenon_bars(
        [
            {"date": "2026-06-29T09:30:00-04:00", "close": 545.10},
            {"date": "2026-06-29T09:35:00-04:00", "close": "545.50"},  # str close
            {"date": "2026-06-29T09:40:00-04:00"},  # missing close → skipped
        ]
    )
    assert len(closes) == 2
    assert closes[datetime(2026, 6, 29, 13, 30, tzinfo=timezone.utc)] == 545.10
    assert closes[datetime(2026, 6, 29, 13, 35, tzinfo=timezone.utc)] == 545.50


def test_join_invariant_apex_utc_matches_uw_et():
    """An Apex bar at 13:30Z must land on the same key a market_tide bar at
    09:30-04:00 (ET wire) normalizes to — that exact-instant match is what the
    backfill UPDATE depends on."""
    closes = _parse_bars([{"time": "2026-06-26T13:30:00+00:00", "close": 727.86}])
    uw_ts = datetime.fromisoformat("2026-06-26T09:30:00-04:00").astimezone(timezone.utc)
    assert closes[uw_ts] == 727.86
