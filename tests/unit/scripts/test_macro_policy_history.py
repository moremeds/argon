"""Unit contract for the resumable 2020+ policy backfill.

Pure decision functions only: which years to run, and whether the run passed.
The database and network paths are exercised by the integration smoke.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.backfill.macro_policy_history import (
    backfill_exit_code,
    resolve_years,
    years_to_run,
)


def _status(
    release_key: str, *, status: str, event_date: date
) -> dict[str, object]:
    return {
        "source": "federal_reserve_fomc",
        "release_key": release_key,
        "status": status,
        "event_date": event_date,
    }


def test_the_durable_window_starts_at_2020():
    """COVID policy and the 2022 hiking cycle define the current regime."""
    assert resolve_years(start_year=2020, end_year=2022) == (2020, 2021, 2022)

    with pytest.raises(ValueError, match="2020"):
        resolve_years(start_year=2019, end_year=2022)


def test_an_inverted_year_span_is_refused_rather_than_silently_empty():
    with pytest.raises(ValueError, match="must not be before"):
        resolve_years(start_year=2024, end_year=2022)


def test_resume_skips_a_past_year_that_fully_succeeded():
    statuses = [
        _status("fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15)),
        _status("fomc-statement:monetary20200429a", status="ok", event_date=date(2020, 4, 29)),
        _status("fomc-statement:monetary20210127a", status="ok", event_date=date(2021, 1, 27)),
    ]

    assert years_to_run(
        (2020, 2021), statuses, current_year=2026, resume=True
    ) == ()


def test_resume_reruns_a_year_holding_any_failure():
    statuses = [
        _status("fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15)),
        _status("fomc-statement:monetary20200429a", status="failed", event_date=date(2020, 4, 29)),
    ]

    assert years_to_run((2020,), statuses, current_year=2026, resume=True) == (2020,)


def test_resume_reruns_a_year_with_evidence_but_no_facts():
    """artifact_only means the bytes landed and the reading never happened."""
    statuses = [
        _status(
            "fomc-statement:monetary20200315a",
            status="artifact_only",
            event_date=date(2020, 3, 15),
        )
    ]

    assert years_to_run((2020,), statuses, current_year=2026, resume=True) == (2020,)


def test_resume_never_skips_the_current_year():
    """The Fed has not finished publishing it, so "complete" cannot be true."""
    statuses = [
        _status("fomc-statement:monetary20260128a", status="ok", event_date=date(2026, 1, 28))
    ]

    assert years_to_run((2026,), statuses, current_year=2026, resume=True) == (2026,)


def test_resume_runs_a_year_never_attempted():
    assert years_to_run((2020,), [], current_year=2026, resume=True) == (2020,)


def test_without_resume_every_requested_year_runs():
    statuses = [
        _status("fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15))
    ]

    assert years_to_run(
        (2020, 2021), statuses, current_year=2026, resume=False
    ) == (2020, 2021)


def test_a_single_failed_release_fails_the_whole_backfill():
    """Partial history is the failure this milestone exists to stop shipping."""
    statuses = [
        _status("fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15)),
        _status("fomc-statement:monetary20200429a", status="failed", event_date=date(2020, 4, 29)),
    ]

    assert backfill_exit_code(statuses) == 1


def test_a_fully_ok_archive_exits_zero():
    statuses = [
        _status("fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15))
    ]

    assert backfill_exit_code(statuses) == 0


def test_an_empty_archive_is_a_failure_not_a_pass():
    """Zero releases means discovery broke; vacuous success hides an outage."""
    assert backfill_exit_code([]) == 1
