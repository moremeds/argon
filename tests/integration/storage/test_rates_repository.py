from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal

import pytest

from uw_scan.models import (
    RatesSnapshotResponse,
    RatesSynthesisPanel,
)
from uw_scan.storage.repository import Repository


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_rates_observations_are_idempotent_across_ingest_runs(repo: Repository):
    rows = [
        {
            "series_id": "DGS10",
            "obs_date": date(2026, 5, 18),
            "value": Decimal("4.47"),
            "realtime_start": date(2026, 5, 20),
            "realtime_end": date(2026, 5, 20),
            "release_date": None,
            "source_url": None,
        }
    ]

    assert (
        repo.upsert_rates_observation_rows(
            rows, seen_at=datetime(2026, 5, 20, 21, tzinfo=UTC), source="FRED"
        )
        == 1
    )
    assert (
        repo.upsert_rates_observation_rows(
            rows, seen_at=datetime(2026, 5, 21, 21, tzinfo=UTC), source="FRED"
        )
        == 1
    )

    fetched = repo.fetch_rates_series("DGS10")
    assert len(fetched) == 1
    assert fetched[0]["value"] == Decimal("4.47")
    assert fetched[0]["last_seen_at"] == datetime(2026, 5, 21, 21, tzinfo=UTC)


def test_rates_observations_normalize_current_fred_vintages(repo: Repository):
    first = {
        "series_id": "DGS10",
        "obs_date": date(2026, 5, 18),
        "value": Decimal("4.47"),
        "realtime_start": date(2026, 5, 20),
        "realtime_end": date(2026, 5, 20),
        "release_date": None,
        "source_url": None,
    }
    revised_current_vintage = {
        **first,
        "value": Decimal("4.48"),
        "realtime_start": date(2026, 5, 21),
        "realtime_end": date(2026, 5, 21),
    }

    repo.upsert_rates_observation_rows(
        [first], seen_at=datetime(2026, 5, 20, 21, tzinfo=UTC), source="FRED"
    )
    repo.upsert_rates_observation_rows(
        [revised_current_vintage],
        seen_at=datetime(2026, 5, 21, 21, tzinfo=UTC),
        source="FRED",
    )

    fetched = repo.fetch_rates_series("DGS10")
    assert len(fetched) == 1
    assert fetched[0]["value"] == Decimal("4.48")
    assert fetched[0]["realtime_start"] == date(2026, 5, 21)
    assert fetched[0]["first_seen_at"] == datetime(2026, 5, 20, 21, tzinfo=UTC)
    assert fetched[0]["last_seen_at"] == datetime(2026, 5, 21, 21, tzinfo=UTC)


def test_rates_snapshot_round_trips_json_native_payload(repo: Repository):
    snapshot = RatesSnapshotResponse(
        as_of=date(2026, 5, 20),
        computed_at=datetime(2026, 5, 20, 21, tzinfo=UTC),
        synthesis=RatesSynthesisPanel(
            duration_view="Live FRED snapshot",
            curve_view="Live curve snapshot",
        ),
    )
    repo.insert_rates_snapshot(
        snapshot_date=snapshot.as_of,
        computed_at=snapshot.computed_at,
        payload=snapshot.model_dump(mode="json"),
        source_freshness=[],
    )

    row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    restored = RatesSnapshotResponse.model_validate(row["payload"])
    assert restored.as_of == date(2026, 5, 20)
    assert restored.computed_at == datetime(2026, 5, 20, 21, tzinfo=UTC)
    assert restored.synthesis.duration_view == "Live FRED snapshot"


def _two_snapshots(repo: Repository) -> None:
    """A pair whose NEWER compute carries the EARLIER market date.

    That inversion is what makes this fixture able to tell the two candidate
    point-in-time columns apart. Ordered by ``snapshot_date`` they rank one way, by
    ``computed_at`` the other, so a query filtering on the wrong one cannot accidentally
    return the right row. Both the latest-wins test and the replay tests stand on it, so
    they cannot drift apart into disagreeing about what "newer" means.
    """
    for market_date, computed_at, view in (
        (date(2026, 5, 20), datetime(2026, 5, 20, 21, tzinfo=UTC), "old compute"),
        (date(2026, 5, 19), datetime(2026, 5, 21, 21, tzinfo=UTC), "new compute"),
    ):
        snapshot = RatesSnapshotResponse(
            as_of=market_date,
            computed_at=computed_at,
            synthesis=RatesSynthesisPanel(duration_view=view, curve_view=view),
        )
        repo.insert_rates_snapshot(
            snapshot_date=snapshot.as_of,
            computed_at=snapshot.computed_at,
            payload=snapshot.model_dump(mode="json"),
            source_freshness=[],
        )


def test_fetch_latest_rates_snapshot_uses_newest_compute_time(repo: Repository):
    _two_snapshots(repo)

    row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    restored = RatesSnapshotResponse.model_validate(row["payload"])
    assert restored.as_of == date(2026, 5, 19)
    assert restored.computed_at == datetime(2026, 5, 21, 21, tzinfo=UTC)
    assert restored.synthesis.duration_view == "new compute"


def test_as_of_filters_on_compute_time_not_on_market_date(repo: Repository):
    """The point-in-time predicate belongs on ``computed_at``.

    A replay asks what the desk COULD HAVE KNOWN at an instant, and ``snapshot_date`` is
    only the market date an answer is about -- the job runs after the close, and a
    backfill can write a row for a market date long after it. Filtered on
    ``snapshot_date <= as_of``, this query would hand a 2026-05-21T00:00Z replay the
    2026-05-19 row, whose ``computed_at`` is a full day IN THE FUTURE of the instant
    being replayed. That is reading tomorrow's answer into the past, which is the exact
    failure point-in-time replay exists to prevent.
    """
    _two_snapshots(repo)

    row = repo.fetch_latest_rates_snapshot(
        as_of=datetime(2026, 5, 21, 0, 0, tzinfo=UTC)
    )

    assert row is not None
    restored = RatesSnapshotResponse.model_validate(row["payload"])
    assert restored.computed_at == datetime(2026, 5, 20, 21, tzinfo=UTC)
    assert restored.as_of == date(2026, 5, 20), (
        "the 2026-05-19 row was not computed until 2026-05-21T21:00Z and could not "
        "have been on the desk"
    )


def test_as_of_before_the_first_compute_finds_nothing(repo: Repository):
    """Absence, not the oldest row. The desk genuinely had no snapshot yet."""
    _two_snapshots(repo)

    assert (
        repo.fetch_latest_rates_snapshot(
            as_of=datetime(2026, 5, 20, 20, 59, tzinfo=UTC)
        )
        is None
    )


def test_no_as_of_is_unchanged_by_the_replay_path(repo: Repository):
    """The live query keeps its shipped answer: newest compute, no predicate."""
    _two_snapshots(repo)

    row = repo.fetch_latest_rates_snapshot()

    assert row is not None
    assert RatesSnapshotResponse.model_validate(row["payload"]).computed_at == datetime(
        2026, 5, 21, 21, tzinfo=UTC
    )
