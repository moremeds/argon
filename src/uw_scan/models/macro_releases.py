"""Weekly economic-release calendar (UW `/api/market/economic-calendar`) with a
point-in-time FRED actual/revision fill. See migration 149 and
`reports/macro_releases.py`.

Kept out of `models/macro.py`: this is a standalone calendar feature, not part
of the MC0-MC3 domain-state engine — no confidence score, no evidence chain,
no composite. `actual`/`series_id` are null whenever we have no verified FRED
mapping for the event; that null IS the coverage statement, never a zero.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from pydantic import AwareDatetime

from ._base import _preserve_public_module, _UwBase


class MacroReleaseRow(_UwBase):
    event: str
    type: str
    reported_period: str
    scheduled_at: AwareDatetime
    forecast: str | None = None
    prior: str | None = None
    #: FRED series backing `actual`, only for a manually verified event->series
    #: mapping (`reports/macro_releases.EVENT_SERIES_MAP`). Null means
    #: unmapped, not unavailable.
    series_id: str | None = None
    actual: Decimal | None = None
    #: True once a later FRED vintage has replaced the first-seen actual for
    #: this release. Always false while `actual` is null.
    revision: bool = False
    #: When `actual` became the published value (FRED `realtime_start`).
    #: Null before the fill job has recorded an actual.
    published_at: AwareDatetime | None = None


class MacroReleaseCalendarResponse(_UwBase):
    week_start: date
    week_end: date
    releases: list[MacroReleaseRow]


_preserve_public_module(MacroReleaseRow, MacroReleaseCalendarResponse)
