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
    """Returns every stubbed row regardless of the observation/vintage window
    asked for -- so the tests prove `fill_actuals` itself selects the right
    period and vintage, rather than trusting FRED's filtering."""

    by_series: dict[str, list[FredObservation]]
    calls: list[tuple[str, dict]] = field(default_factory=list)

    def fetch_observations(self, series_id: str, **kwargs) -> list[FredObservation]:
        self.calls.append((series_id, kwargs))
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


def _obs(obs_date: date, value: str, realtime_start: date) -> FredObservation:
    return FredObservation(
        series_id="UNRATE",
        obs_date=obs_date,
        value=Decimal(value),
        realtime_start=realtime_start,
        realtime_end=date(2026, 12, 31),
    )


def test_fill_actuals_fills_the_reported_period_and_asks_for_its_vintage():
    fred = _StubFred(
        by_series={
            "UNRATE": [
                _obs(date(2026, 7, 1), "4.2", date(2026, 8, 1)),
                _obs(date(2026, 8, 1), "4.3", date(2026, 9, 5)),
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
    assert fred.calls == [
        (
            "UNRATE",
            {
                "start": date(2026, 8, 1),
                "end": date(2026, 8, 1),
                "realtime_start": date(2026, 9, 4),
                "realtime_end": date(2026, 9, 10),
            },
        )
    ]


def test_fill_actuals_backfill_gets_its_own_period_not_freds_latest():
    """Regression: a late run / backfill for a release two periods older than
    FRED's newest observation must fill THAT release's period. The old code
    took `max(obs_date)` and filled June's release with August's value."""
    fred = _StubFred(
        by_series={
            "UNRATE": [
                _obs(date(2026, 6, 1), "4.2", date(2026, 7, 3)),
                _obs(date(2026, 7, 1), "4.2", date(2026, 8, 1)),
                _obs(date(2026, 8, 1), "4.3", date(2026, 9, 5)),
            ]
        }
    )
    june = {
        **_ROW,
        "scheduled_at": datetime(2026, 7, 3, 12, tzinfo=UTC),
        "reported_period": "June",
    }
    repo = _StubRepo([june])

    fill_actuals(repo, fred, as_of=datetime(2026, 9, 10, tzinfo=UTC))

    [row] = repo.filled
    assert row["actual"] == Decimal("4.2")
    assert row["published_at"] == datetime(2026, 7, 3, tzinfo=UTC)


def test_fill_actuals_records_the_first_print_not_the_revision():
    fred = _StubFred(
        by_series={
            "UNRATE": [
                _obs(date(2026, 8, 1), "4.2", date(2026, 10, 2)),  # revision
                _obs(date(2026, 8, 1), "4.3", date(2026, 9, 5)),  # first print
            ]
        }
    )
    repo = _StubRepo([_ROW])

    fill_actuals(repo, fred, as_of=datetime(2026, 10, 10, tzinfo=UTC))

    [row] = repo.filled
    assert row["actual"] == Decimal("4.3")
    assert row["published_at"] == datetime(2026, 9, 5, tzinfo=UTC)


def test_fill_actuals_december_released_in_january_is_the_prior_year():
    fred = _StubFred(
        by_series={"UNRATE": [_obs(date(2026, 12, 1), "4.3", date(2027, 1, 8))]}
    )
    dec = {
        **_ROW,
        "scheduled_at": datetime(2027, 1, 8, 13, tzinfo=UTC),
        "reported_period": "December",
    }
    repo = _StubRepo([dec])

    assert fill_actuals(repo, fred, as_of=datetime(2027, 1, 9, tzinfo=UTC)) == 1


def test_fill_actuals_skips_a_release_fred_has_not_published_yet():
    """The target period's observation exists but its realtime_start is AFTER
    `as_of` -- not yet known. An OLDER period is already known; the row must
    still be left unfilled rather than take that neighbour's value."""
    fred = _StubFred(
        by_series={
            "UNRATE": [
                _obs(date(2026, 7, 1), "4.2", date(2026, 8, 1)),
                _obs(date(2026, 8, 1), "4.3", date(2026, 9, 5)),
            ]
        }
    )
    repo = _StubRepo([_ROW])

    filled = fill_actuals(repo, fred, as_of=datetime(2026, 9, 4, 13, tzinfo=UTC))

    assert filled == 0
    assert repo.filled == []


def test_fill_actuals_leaves_an_unparseable_period_unfilled():
    fred = _StubFred(
        by_series={"UNRATE": [_obs(date(2026, 8, 1), "4.3", date(2026, 9, 5))]}
    )
    for label in ("Q3", "September"):  # not a month / the release's own month
        repo = _StubRepo([{**_ROW, "reported_period": label}])
        assert fill_actuals(repo, fred, as_of=datetime(2026, 9, 10, tzinfo=UTC)) == 0
    assert fred.calls == []


def test_fill_actuals_skips_when_fred_has_no_observation_at_all():
    fred = _StubFred(by_series={})
    repo = _StubRepo([_ROW])

    filled = fill_actuals(repo, fred, as_of=datetime(2026, 9, 10, tzinfo=UTC))

    assert filled == 0
    assert repo.filled == []
