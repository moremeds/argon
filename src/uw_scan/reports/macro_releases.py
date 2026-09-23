"""Weekly economic-release calendar: capture UW's forecast/prior, fill a FRED
actual for the small set of events we've manually verified match FRED's unit
and transform. See migration 149 and `storage/macro_release_calendar.py`.

Deliberately outside `macro/` -- this is a standalone calendar, not an MC0-MC3
domain state (no confidence score, no evidence chain, no composite).
"""

from __future__ import annotations

import logging
from calendar import month_name
from datetime import UTC, date, datetime, timedelta

from uw_scan.models import MacroReleaseCalendarResponse, MacroReleaseRow
from uw_scan.sources.fred import FredProvider
from uw_scan.storage.macro_release_calendar import MacroReleaseCalendarRepository

logger = logging.getLogger(__name__)

#: Verified event(lowercased) -> FRED series id, each checked by hand for unit
#: AND transform match against UW's forecast/prev text before being added --
#: see the CLAUDE.md "No fabrication" rule. Do not add an entry on a guess;
#: `PAYEMS` for example is a level series while UW reports the MoM change, so
#: it is deliberately absent rather than wired to a wrong number.
EVENT_SERIES_MAP: dict[str, str] = {
    "unemployment rate": "UNRATE",
}


_MONTHS: dict[str, int] = {name.lower(): i for i, name in enumerate(month_name) if name}


def week_bounds(week_start: date) -> tuple[datetime, datetime]:
    """[Monday 00:00 UTC, +7 days) for the week containing `week_start`."""
    monday = week_start - timedelta(days=week_start.weekday())
    start = datetime.combine(monday, datetime.min.time(), UTC)
    return start, start + timedelta(days=7)


def week_releases(
    repo: MacroReleaseCalendarRepository, week_start: date
) -> MacroReleaseCalendarResponse:
    start, end = week_bounds(week_start)
    rows = repo.week(start=start, end=end)
    return MacroReleaseCalendarResponse(
        week_start=start.date(),
        week_end=(end - timedelta(days=1)).date(),
        releases=[
            MacroReleaseRow(
                event=r["event"],
                type=r["type"],
                reported_period=r["reported_period"],
                scheduled_at=r["scheduled_at"],
                forecast=r["forecast"],
                prior=r["prior"],
                series_id=r["series_id"],
                actual=r["actual"],
                revision=r["revision"],
                published_at=r["published_at"],
            )
            for r in rows
        ],
    )


def _target_obs_date(reported_period: str, scheduled_at: datetime) -> date | None:
    """UW's month label (e.g. "December") -> the FRED monthly `obs_date` it
    names: the most recent first-of-that-month strictly before the release's
    own month (a December print released in January is the prior year's).
    Anything that isn't a bare English month name, or that names the
    release's own month, returns None -- unfilled, never guessed."""
    month = _MONTHS.get(reported_period.strip().lower())
    if month is None or month == scheduled_at.month:
        return None
    year = scheduled_at.year if month < scheduled_at.month else scheduled_at.year - 1
    return date(year, month, 1)


def fill_actuals(
    repo: MacroReleaseCalendarRepository,
    fred: FredProvider,
    *,
    as_of: datetime | None = None,
) -> int:
    """For every past, unfilled, mapped release, record FRED's FIRST PRINT of
    the observation `reported_period` names. Returns rows filled.

    The first print is read from an ALFRED vintage window opening on the
    release date: the target observation's earliest row there is the value
    the market saw, not today's revision. A release whose exact observation
    FRED hasn't published yet (as of `as_of`), or whose period label doesn't
    parse, is left unfilled and retried on the next run -- never filled with
    a neighbouring period's value.
    """
    now = as_of or datetime.now(UTC)
    candidates = repo.unfilled_mapped(series_ids=EVENT_SERIES_MAP, before=now)
    filled = 0
    for row in candidates:
        target = _target_obs_date(row["reported_period"], row["scheduled_at"])
        if target is None:
            logger.warning(
                "macro_release_calendar: unparseable reported_period %r for %s",
                row["reported_period"],
                row["event"],
            )
            continue
        try:
            observations = fred.fetch_observations(
                row["series_id"],
                start=target,
                end=target,
                realtime_start=row["scheduled_at"].date(),
                realtime_end=now.date(),
            )
        except Exception:
            logger.exception(
                "macro_release_calendar: FRED fetch failed for %s", row["series_id"]
            )
            continue
        known = [
            o
            for o in observations
            if o.obs_date == target
            and o.realtime_start is not None
            and o.realtime_start <= now.date()
        ]
        if not known:
            continue
        first = min(known, key=lambda o: o.realtime_start)
        repo.fill_actual(
            event=row["event"],
            scheduled_at=row["scheduled_at"],
            series_id=row["series_id"],
            actual=first.value,
            published_at=datetime.combine(
                first.realtime_start, datetime.min.time(), UTC
            ),
        )
        filled += 1
    return filled
