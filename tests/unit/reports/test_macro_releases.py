"""Pure-function pieces of the weekly release-calendar report: week bounds and
the FRED fill loop. No DB, no network -- the repo/FRED boundaries are stubbed
with plain objects, not mocked cursors (storage/CLAUDE.md's ban is on faking
the DB inside a DB test; this never touches Postgres)."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime
from decimal import Decimal

from uw_scan.reports.macro_releases import fill_actuals, week_bounds
from uw_scan.sources.fred import FredObservation


def test_week_bounds_finds_the_containing_mondays_range():
    start, end = week_bounds(date(2026, 9, 4))  # a Friday
    assert start == datetime(2026, 8, 31, tzinfo=UTC)  # Monday
    assert end == datetime(2026, 9, 7, tzinfo=UTC)


def test_week_bounds_on_a_monday_starts_that_day():
    start, end = week_bounds(date(2026, 9, 7))
    assert start == datetime(2026, 9, 7, tzinfo=UTC)
    assert end == datetime(2026, 9, 14, tzinfo=UTC)


@dataclass
class _StubFred:
    by_series: dict[str, list[FredObservation]]
    calls: list[str] = field(default_factory=list)

    def fetch_observations(self, series_id: str) -> list[FredObservation]:
        self.calls.append(series_id)
        return self.by_series.get(series_id, [])


class _StubRepo:
    def __init__(self, candidates: list[dict]) -> None:
        self._candidates = candidates
        self.filled: list[dict] = []

    def unfilled_mapped(self, *, series_ids, before):
        return self._candidates

    def fill_actual(self, **kwargs):
        self.filled.append(kwargs)


_ROW = {
    "event": "Unemployment rate",
    "scheduled_at": datetime(2026, 9, 4, 12, tzinfo=UTC),
    "reported_period": "August",
    "series_id": "UNRATE",
}


def test_fill_actuals_uses_the_latest_observation_already_known_as_of():
    fred = _StubFred(
        by_series={
            "UNRATE": [
                FredObservation(
                    series_id="UNRATE",
                    obs_date=date(2026, 7, 1),
                    value=Decimal("4.2"),
                    realtime_start=date(2026, 8, 1),
                    realtime_end=date(2026, 12, 31),
                ),
                FredObservation(
                    series_id="UNRATE",
                    obs_date=date(2026, 8, 1),
                    value=Decimal("4.3"),
                    realtime_start=date(2026, 9, 5),
                    realtime_end=date(2026, 12, 31),
                ),
            ]
        }
    )
    repo = _StubRepo([_ROW])

    filled = fill_actuals(repo, fred, as_of=datetime(2026, 9, 10, tzinfo=UTC))

    assert filled == 1
    assert repo.filled == [
        {
            "event": "Unemployment rate",
            "scheduled_at": _ROW["scheduled_at"],
            "series_id": "UNRATE",
            "actual": Decimal("4.3"),
            "published_at": datetime(2026, 9, 5, tzinfo=UTC),
        }
    ]


def test_fill_actuals_skips_a_release_fred_has_not_published_yet():
    """FRED's observation exists but its realtime_start is AFTER `as_of` --
    not yet known -- so the row must be left unfilled, not backfilled with a
    future-published value."""
    fred = _StubFred(
        by_series={
            "UNRATE": [
                FredObservation(
                    series_id="UNRATE",
                    obs_date=date(2026, 8, 1),
                    value=Decimal("4.3"),
                    realtime_start=date(2026, 9, 5),
                    realtime_end=date(2026, 12, 31),
                )
            ]
        }
    )
    repo = _StubRepo([_ROW])

    filled = fill_actuals(repo, fred, as_of=datetime(2026, 9, 4, tzinfo=UTC))

    assert filled == 0
    assert repo.filled == []


def test_fill_actuals_skips_when_fred_has_no_observation_at_all():
    fred = _StubFred(by_series={})
    repo = _StubRepo([_ROW])

    filled = fill_actuals(repo, fred, as_of=datetime(2026, 9, 10, tzinfo=UTC))

    assert filled == 0
    assert repo.filled == []
