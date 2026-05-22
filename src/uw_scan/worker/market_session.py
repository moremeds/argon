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
    if local.weekday() >= 5:
        return None
    current = local.time()
    if time(4, 0) <= current <= time(20, 0):
        return local.date()
    return None
