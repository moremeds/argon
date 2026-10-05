"""Pure parts of the dark/lit history backfill: budget-day quota, the pending
list (oldest first, complete/truncated rule, finished + out-of-window skips), and
parsing UW's out-of-window answer."""

from __future__ import annotations

from datetime import UTC, date, datetime
from types import SimpleNamespace

from uw_scan.api.client import UwHTTPError
from uw_scan.worker.jobs.dark_lit_backfill import (
    _out_of_window,
    day_quota,
    pending_ticker_days,
)

_S = SimpleNamespace(
    dark_lit_backfill_weekday_max_calls=15000,
    dark_lit_backfill_saturday_max_calls=60000,
    dark_lit_backfill_sunday_max_calls=50000,
)


def test_quota_follows_the_utc_budget_day():
    # Friday 22:30 EDT is 02:30 UTC Saturday: the Friday-evening run is Saturday's.
    assert day_quota(_S, datetime(2026, 10, 10, 2, 30, tzinfo=UTC)) == 60000
    assert day_quota(_S, datetime(2026, 10, 11, 2, 30, tzinfo=UTC)) == 50000
    # Sunday 22:30 EDT is Monday UTC: weekday cap.
    assert day_quota(_S, datetime(2026, 10, 12, 2, 30, tzinfo=UTC)) == 15000
    # Friday 19:00 EDT is still Friday UTC.
    assert day_quota(_S, datetime(2026, 10, 9, 23, 0, tzinfo=UTC)) == 15000


D1, D2, D3 = date(2023, 11, 2), date(2023, 11, 3), date(2023, 11, 6)


def test_pending_is_oldest_first_and_skips_complete_days():
    counts = {
        (D1, "AAA"): (120, 30),  # both under a page: never cut, skip
        (D1, "BBB"): (500, 10),  # dark hit the page: cut, refetch
        (D2, "AAA"): (10, 500),  # lit hit the page: cut, refetch
    }
    got = pending_ticker_days([D3, D1, D2], ["BBB", "AAA"], counts, set(), None)
    assert got == [
        (D1, "BBB"),
        (D2, "AAA"),
        (D2, "BBB"),  # missing entirely
        (D3, "AAA"),
        (D3, "BBB"),
    ]


def test_pending_skips_finished_and_out_of_window_days():
    finished = {(D2, "AAA")}
    got = pending_ticker_days([D1, D2, D3], ["AAA"], {}, finished, floor=D1)
    assert got == [(D3, "AAA")]


# Verbatim UW answer for an out-of-window date (probe 2026-10-05, AAPL 2023-10-31).
_MSG = (
    '{"code":"historic_data_access_missing","message":"The earliest date currently '
    "available to this token is 2023-11-02 (730 trading days), so 2023-10-31 in "
    'query param date will not return historical data."}'
)


def test_out_of_window_parses_the_earliest_date():
    assert _out_of_window(UwHTTPError(403, "darkpool_ticker", _MSG)) == D1
    reworded = '{"code":"historic_data_access_missing","message":"no"}'
    assert _out_of_window(UwHTTPError(403, "x", reworded)) == date.min
    assert _out_of_window(UwHTTPError(403, "x", '{"code":"forbidden"}')) is None
    assert _out_of_window(UwHTTPError(500, "x", _MSG)) is None
    assert _out_of_window(ValueError("x")) is None
