"""Unit tests for the record-coverage market-session gate.

The integration health tests all monkeypatch `_record_window_scans_expected`
so their coverage assertions are deterministic; this file exercises the real
computation (cron parsing + US-market-day filter) directly.
"""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from uw_scan.api.routers.health import _record_window_scans_expected
from uw_scan.config import Settings

# Exercise the real configured crons + tz without constructing a full Settings
# (which requires api_key / DB env). The helper only reads these two attributes.
_SETTINGS = SimpleNamespace(
    full_scan_crons=Settings.model_fields["full_scan_crons"].get_default(
        call_default_factory=True
    ),
    rth_tz=Settings.model_fields["rth_tz"].get_default(call_default_factory=True),
)


def test_scans_expected_during_rth_weekday():
    # Wed 2026-05-13 14:00 ET (18:00 UTC): the 8h window (06:00-14:00 ET) spans
    # the premarket + open + RTH crons, all on a regular market day.
    now = datetime(2026, 5, 13, 18, 0, tzinfo=UTC)
    assert (
        _record_window_scans_expected(_SETTINGS, now_utc=now, record_window_hours=8)
        is True
    )


def test_no_scans_expected_on_weekend():
    # Sat 2026-07-04 14:00 ET: market closed, no crons fire.
    now = datetime(2026, 7, 4, 18, 0, tzinfo=UTC)
    assert (
        _record_window_scans_expected(_SETTINGS, now_utc=now, record_window_hours=8)
        is False
    )


def test_no_scans_expected_on_observed_holiday():
    # Fri 2026-07-03 14:00 ET: Independence Day observed — a full-day closure
    # even though it is a weekday, so is_us_equity_market_day() excludes it.
    now = datetime(2026, 7, 3, 18, 0, tzinfo=UTC)
    assert (
        _record_window_scans_expected(_SETTINGS, now_utc=now, record_window_hours=8)
        is False
    )


def test_none_window_is_not_expected():
    now = datetime(2026, 5, 13, 18, 0, tzinfo=UTC)
    assert (
        _record_window_scans_expected(_SETTINGS, now_utc=now, record_window_hours=None)
        is False
    )
