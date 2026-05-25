"""Market-session helpers.

Pure functions; no DB or network. Shared by the WS consumer's OHLC cache
key (worker/ws_db_writer.py) and the API health endpoint so both agree on
"is the US equity market open right now?".

Phase 7 will delete the duplicate ``_spot_refresh_market_date`` in
``worker/scheduler.py`` and update its callers to import from here. Until
then this module is purely additive — no caller is forced to switch.
"""

from __future__ import annotations

from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo


def current_market_date(now: datetime, tz: str = "America/New_York") -> date | None:
    """Return the ET market date when the equity session is feed-active.

    Returns ``None`` outside the pre-market / RTH / after-hours window
    (mon-fri 04:00-20:00 ET). Outside the window callers should fall back
    to the most recent prior weekday for cache stability.

    The window is set to match massive.com's per-second aggregate feed,
    which covers "pre-market, regular, and after-hours sessions" per
    https://massive.com/docs/websocket/stocks/aggregates-per-second.
    Using a tighter RTH-only window would mislabel pre-market 04:00-09:30
    as "market closed" in /api/health even while ticks are flowing.
    """
    local = (
        now.astimezone(ZoneInfo(tz))
        if now.tzinfo is not None
        else now.replace(tzinfo=ZoneInfo(tz))
    )
    if not is_us_equity_market_day(local.date()):
        return None
    current = local.time()
    if time(4, 0) <= current <= time(20, 0):
        return local.date()
    return None


def is_us_equity_market_day(day: date) -> bool:
    """Return true for regular NYSE trading days.

    This intentionally covers scheduled full-day closures only. It does not
    model ad-hoc closures or half days; half days still count as market days
    because the full-scan scheduler should run at least one batch.
    """
    return day.weekday() < 5 and day not in _nyse_holidays(day.year)


def _nyse_holidays(year: int) -> set[date]:
    holidays: set[date] = set()
    for candidate_year in (year - 1, year, year + 1):
        holidays.update(_nyse_holidays_for_year(candidate_year))
    return {holiday for holiday in holidays if holiday.year == year}


def _nyse_holidays_for_year(year: int) -> set[date]:
    holidays = {
        _observed(date(year, 1, 1)),
        _nth_weekday(year, 1, 0, 3),  # Martin Luther King Jr. Day
        _nth_weekday(year, 2, 0, 3),  # Washington's Birthday
        _easter_date(year) - timedelta(days=2),  # Good Friday
        _last_weekday(year, 5, 0),  # Memorial Day
        _observed(date(year, 7, 4)),
        _nth_weekday(year, 9, 0, 1),  # Labor Day
        _nth_weekday(year, 11, 3, 4),  # Thanksgiving
        _observed(date(year, 12, 25)),
    }
    if year >= 2022:
        holidays.add(_observed(date(year, 6, 19)))  # Juneteenth
    return holidays


def _observed(day: date) -> date:
    if day.weekday() == 5:
        return day - timedelta(days=1)
    if day.weekday() == 6:
        return day + timedelta(days=1)
    return day


def _nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    current = date(year, month, 1)
    offset = (weekday - current.weekday()) % 7
    return current + timedelta(days=offset + 7 * (n - 1))


def _last_weekday(year: int, month: int, weekday: int) -> date:
    if month == 12:
        current = date(year + 1, 1, 1) - timedelta(days=1)
    else:
        current = date(year, month + 1, 1) - timedelta(days=1)
    return current - timedelta(days=(current.weekday() - weekday) % 7)


def _easter_date(year: int) -> date:
    """Gregorian Easter date using the Meeus/Jones/Butcher algorithm."""
    a = year % 19
    b = year // 100
    c = year % 100
    d = b // 4
    e = b % 4
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i = c // 4
    k = c % 4
    weekday_adjustment = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * weekday_adjustment) // 451
    month = (h + weekday_adjustment - 7 * m + 114) // 31
    day = ((h + weekday_adjustment - 7 * m + 114) % 31) + 1
    return date(year, month, day)
