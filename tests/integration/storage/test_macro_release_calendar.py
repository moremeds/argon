"""Weekly economic-release calendar store (migration 149): the UW capture
path and the FRED fill path write disjoint columns on the same row, and
revision detection is keyed off the first-recorded actual, never the latest.
"""

from __future__ import annotations

from datetime import UTC, datetime
from decimal import Decimal

from uw_scan.storage.macro_release_calendar import MacroReleaseCalendarRepository

_SCHEDULED_AT = datetime(2026, 9, 4, 12, 30, tzinfo=UTC)


def _repo(seeded) -> MacroReleaseCalendarRepository:
    return MacroReleaseCalendarRepository(seeded.conn, schema=seeded._schema)


def _captured_row(**over) -> dict:
    row = {
        "event": "Unemployment rate",
        "scheduled_at": _SCHEDULED_AT,
        "type": "report",
        "reported_period": "August",
        "forecast": "4.3%",
        "prior": "4.2%",
    }
    row.update(over)
    return row


def test_capture_replay_reports_zero_new_rows(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    assert repo.upsert_captured_rows([_captured_row()]) == 1
    assert repo.upsert_captured_rows([_captured_row()]) == 0


def test_capture_replay_refreshes_forecast_in_place(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_captured_rows([_captured_row(forecast="4.3%")])
    repo.upsert_captured_rows([_captured_row(forecast="4.4%")])

    [row] = repo.week(
        start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert row["forecast"] == "4.4%"


def test_unfilled_mapped_only_returns_known_events_before_the_cutoff(
    seeded_db_empty_cards,
):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_captured_rows(
        [
            _captured_row(event="Unemployment rate"),
            _captured_row(event="Nonfarm payrolls", scheduled_at=_SCHEDULED_AT),
        ]
    )

    candidates = repo.unfilled_mapped(
        series_ids={"unemployment rate": "UNRATE"},
        before=datetime(2026, 9, 5, tzinfo=UTC),
    )
    assert [c["event"] for c in candidates] == ["Unemployment rate"]
    assert candidates[0]["series_id"] == "UNRATE"

    # A release scheduled AFTER the cutoff (not yet happened) is excluded even
    # though its event is mapped.
    future = repo.unfilled_mapped(
        series_ids={"unemployment rate": "UNRATE"},
        before=datetime(2026, 9, 3, tzinfo=UTC),
    )
    assert future == []


def test_fill_actual_first_seen_pins_the_revision_baseline(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_captured_rows([_captured_row()])
    published = datetime(2026, 9, 5, 12, tzinfo=UTC)

    repo.fill_actual(
        event="Unemployment rate",
        scheduled_at=_SCHEDULED_AT,
        series_id="UNRATE",
        actual=Decimal("4.3"),
        published_at=published,
    )
    [row] = repo.week(
        start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert row["actual"] == Decimal("4.3")
    assert row["revision"] is False
    assert row["published_at"] == published

    # A later fill with a DIFFERENT value is a revision -- detected against
    # the first-seen value, not against the previous fill.
    repo.fill_actual(
        event="Unemployment rate",
        scheduled_at=_SCHEDULED_AT,
        series_id="UNRATE",
        actual=Decimal("4.4"),
        published_at=datetime(2026, 10, 3, tzinfo=UTC),
    )
    [row] = repo.week(
        start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert row["actual"] == Decimal("4.4")
    assert row["revision"] is True

    # A THIRD fill back to the original value is still a revision relative
    # to the pinned first-seen baseline, not "no change from last time".
    repo.fill_actual(
        event="Unemployment rate",
        scheduled_at=_SCHEDULED_AT,
        series_id="UNRATE",
        actual=Decimal("4.3"),
        published_at=datetime(2026, 11, 3, tzinfo=UTC),
    )
    [row] = repo.week(
        start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert row["revision"] is False


def test_week_excludes_rows_outside_the_bound(seeded_db_empty_cards):
    repo = _repo(seeded_db_empty_cards)
    repo.upsert_captured_rows(
        [
            _captured_row(event="In week", scheduled_at=_SCHEDULED_AT),
            _captured_row(
                event="Next week", scheduled_at=datetime(2026, 9, 9, tzinfo=UTC)
            ),
        ]
    )
    rows = repo.week(
        start=datetime(2026, 9, 1, tzinfo=UTC), end=datetime(2026, 9, 8, tzinfo=UTC)
    )
    assert [r["event"] for r in rows] == ["In week"]
