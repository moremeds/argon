"""Port of xenon/src/xenon/analysis/gex.py:122 - is_opex_week."""

from __future__ import annotations

from datetime import date, timedelta


def is_opex_week(today: date) -> bool:
    """True if `today` is within 3 calendar days before the 3rd Friday."""
    first_day = today.replace(day=1)
    first_friday_offset = (4 - first_day.weekday()) % 7
    third_friday = first_day + timedelta(days=first_friday_offset + 14)
    delta = (third_friday - today).days
    return 0 <= delta <= 3
