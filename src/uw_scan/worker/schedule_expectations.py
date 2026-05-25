"""Expected scheduler fire helpers with market-day awareness."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger

from uw_scan.worker.market_session import is_us_equity_market_day


def expected_market_cron_fires_between(
    cron_exprs: list[str],
    tz: str,
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> list[datetime]:
    """Return scheduled fires after ``start_utc`` through ``end_utc``.

    Full scans are only expected on regular US equity market days. Weekends and
    full-day public holidays are excluded so observability does not page on
    planned market closures.
    """
    if end_utc <= start_utc:
        return []

    start = _as_utc(start_utc)
    end = _as_utc(end_utc)
    local_tz = ZoneInfo(tz)
    fires: list[datetime] = []

    for expr in cron_exprs:
        trigger = CronTrigger.from_crontab(expr, timezone=local_tz)
        previous = None
        current = trigger.get_next_fire_time(previous, start - timedelta(seconds=1))
        while current is not None and current <= end:
            current_utc = _as_utc(current)
            if current_utc > start and is_us_equity_market_day(
                current.astimezone(local_tz).date()
            ):
                fires.append(current_utc)
            previous = current
            current = trigger.get_next_fire_time(previous, previous)

    return sorted(fires)


def latest_expected_market_cron_fire(
    cron_exprs: list[str],
    tz: str,
    *,
    now_utc: datetime,
    lookback_days: int = 14,
) -> datetime | None:
    fires = expected_market_cron_fires_between(
        cron_exprs,
        tz,
        start_utc=now_utc - timedelta(days=lookback_days),
        end_utc=now_utc,
    )
    return fires[-1] if fires else None


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)
