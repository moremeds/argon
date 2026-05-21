"""Market-session helpers.

Pure functions; no DB or network. Shared by the WS consumer's OHLC cache
key (worker/ws_db_writer.py) and the API health endpoint so both agree on
"is the US equity market open right now?".

Phase 7 will delete the duplicate ``_spot_refresh_market_date`` in
``worker/scheduler.py`` and update its callers to import from here. Until
then this module is purely additive — no caller is forced to switch.
"""

from __future__ import annotations

from datetime import date, datetime, time
from zoneinfo import ZoneInfo


def current_market_date(now: datetime, tz: str = "America/New_York") -> date | None:
    """Return the ET market date when the equity session is open / active.

    Returns ``None`` outside the RTH-plus-late-print window (mon-fri
    09:30-20:15 ET). Outside the window callers should fall back to the
    most recent prior weekday for cache stability.

    Matches the behavior of ``_spot_refresh_market_date`` in
    ``worker/scheduler.py`` (the source of truth pre-Phase 7).
    """
    local = (
        now.astimezone(ZoneInfo(tz))
        if now.tzinfo is not None
        else now.replace(tzinfo=ZoneInfo(tz))
    )
    if local.weekday() >= 5:
        return None
    current = local.time()
    if time(9, 30) <= current <= time(20, 15):
        return local.date()
    return None
