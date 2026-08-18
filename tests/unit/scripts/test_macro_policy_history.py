"""Unit contract for the resumable 2020+ policy backfill.

Pure decision functions only: which years to run, and whether the run passed.
The database and network paths are exercised by the integration smoke.
"""

from __future__ import annotations

from datetime import date

import pytest

from scripts.backfill.macro_policy_history import (
    backfill_exit_code,
    missing_coverage,
    resolve_years,
    years_to_run,
)


def _status(
    release_key: str,
    *,
    status: str,
    event_date: date,
    source: str = "federal_reserve_fomc",
) -> dict[str, object]:
    return {
        "source": source,
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


def _complete_2020() -> list[dict[str, object]]:
    """One ok release per source for 2020 — the minimum a covered year needs."""
    return [
        _status(
            "fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15)
        ),
        _status(
            "fed-sep:20200610",
            status="ok",
            event_date=date(2020, 6, 10),
            source="federal_reserve_sep",
        ),
    ]


def test_a_single_failed_release_fails_the_whole_backfill():
    """Partial history is the failure this milestone exists to stop shipping."""
    statuses = _complete_2020() + [
        _status(
            "fomc-statement:monetary20200429a",
            status="failed",
            event_date=date(2020, 4, 29),
        ),
    ]

    assert backfill_exit_code(statuses, years=(2020,), current_year=2026) == 1


def test_a_fully_ok_archive_exits_zero():
    assert (
        backfill_exit_code(_complete_2020(), years=(2020,), current_year=2026) == 0
    )


def test_an_empty_archive_is_a_failure_not_a_pass():
    """Zero releases means discovery broke; vacuous success hides an outage."""
    assert backfill_exit_code([], years=(2020,), current_year=2026) == 1


def test_a_past_year_that_produced_nothing_fails_even_when_every_row_is_ok():
    """The rows are the numerator; the requested window is the denominator.

    A year whose discovery failed writes NO catalog rows, so it vanishes from
    the filter and takes its own evidence with it.  Judging the run by the rows
    that exist passes over exactly the hole worth catching.
    """
    statuses = _complete_2020()

    assert backfill_exit_code(statuses, years=(2020, 2021), current_year=2026) == 1
    assert missing_coverage(statuses, years=(2020, 2021), current_year=2026) == [
        "federal_reserve_fomc:2021",
        "federal_reserve_sep:2021",
    ]


def test_one_source_going_dark_for_a_year_is_not_hidden_by_the_other():
    """SEP publishes 4 times a year against the FOMC's 8.

    Requiring only "the year has rows" would let a whole SEP outage hide behind
    a healthy statement feed.
    """
    statuses = [
        _status(
            "fomc-statement:monetary20200315a", status="ok", event_date=date(2020, 3, 15)
        )
    ]

    assert missing_coverage(statuses, years=(2020,), current_year=2026) == [
        "federal_reserve_sep:2020"
    ]


def test_the_current_year_is_never_required_to_have_published_yet():
    """In January a source legitimately has zero releases.

    An exit code that cries wolf every January is one the operator learns to
    ignore, which costs more than the case it catches.
    """
    statuses = _complete_2020()

    assert missing_coverage(statuses, years=(2020, 2026), current_year=2026) == []
    assert backfill_exit_code(statuses, years=(2020, 2026), current_year=2026) == 0
