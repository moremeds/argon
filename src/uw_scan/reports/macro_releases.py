"""Weekly economic-release calendar: capture UW's forecast/prior, fill a FRED
actual for the small set of events we've manually verified match FRED's unit
and transform. See migration 149 and `storage/macro_release_calendar.py`.

Deliberately outside `macro/` -- this is a standalone calendar, not an MC0-MC3
domain state (no confidence score, no evidence chain, no composite).
"""

from __future__ import annotations

import logging
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


def fill_actuals(
    repo: MacroReleaseCalendarRepository,
    fred: FredProvider,
    *,
    as_of: datetime | None = None,
) -> int:
    """For every past, unfilled, mapped release, look up FRED's observation
    for `reported_period` and record it. Returns rows filled.

    `reported_period` is UW's free-text month/quarter label (e.g.
    "December") -- matched to a FRED `obs_date` by taking the latest
    observation FRED had already published as of `as_of` for that series.
    A release with no matching FRED observation yet (FRED hasn't published
    this period) is left unfilled and retried on the next run.
    """
    now = as_of or datetime.now(UTC)
    candidates = repo.unfilled_mapped(series_ids=EVENT_SERIES_MAP, before=now)
    filled = 0
    for row in candidates:
        try:
            observations = fred.fetch_observations(row["series_id"])
        except Exception:
            logger.exception(
                "macro_release_calendar: FRED fetch failed for %s", row["series_id"]
            )
            continue
        known = [
            o
            for o in observations
            if o.realtime_start is not None and o.realtime_start <= now.date()
        ]
        if not known:
            continue
        latest = max(known, key=lambda o: o.obs_date)
        repo.fill_actual(
            event=row["event"],
            scheduled_at=row["scheduled_at"],
            series_id=row["series_id"],
            actual=latest.value,
            published_at=datetime.combine(
                latest.realtime_start, datetime.min.time(), UTC
            ),
        )
        filled += 1
    return filled
