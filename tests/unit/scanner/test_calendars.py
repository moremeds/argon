"""is_opex_week port — verifies 3rd-Friday-of-month detection."""

from __future__ import annotations

from datetime import date

from uw_scan.scanner.calendars import is_opex_week


def test_opex_week_third_friday_returns_true():
    # 2025-12-19 was the 3rd Friday of Dec 2025
    assert is_opex_week(date(2025, 12, 19)) is True


def test_three_days_before_third_friday_is_opex_week():
    # 2025-12-16 is Tuesday — 3 days before 3rd-Friday Dec 19
    assert is_opex_week(date(2025, 12, 16)) is True


def test_more_than_three_days_before_third_friday_is_not_opex_week():
    # 2025-12-15 is Monday — 4 days before; outside window
    assert is_opex_week(date(2025, 12, 15)) is False


def test_day_after_third_friday_not_opex_week():
    assert is_opex_week(date(2025, 12, 20)) is False


def test_january_2026_third_friday():
    # 2026-01-16 is 3rd Friday of January
    assert is_opex_week(date(2026, 1, 16)) is True
    assert is_opex_week(date(2026, 1, 13)) is True  # Tuesday, 3 days before
    assert is_opex_week(date(2026, 1, 12)) is False
