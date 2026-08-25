"""Parsing SEC submissions into filing evidence.

Frozen from NVDA's real submissions payload, 2026-08-24. The amendment rows are
the load-bearing ones: a period carrying a `/A` is a period where Argon cannot
tell which content version it holds, and the whole rule turns on detecting them.
"""

from __future__ import annotations

from datetime import date

from uw_scan.sources.sec_submissions import (
    SecFiling,
    archive_names,
    parse_archive,
    parse_submissions,
)

PAYLOAD = {
    "filings": {
        "recent": {
            "accessionNumber": [
                "0001045810-26-000052",
                "0001045810-26-000021",
                "0001045810-25-000230",
                "0000891618-04-000000",
                "0001045810-24-000316",
            ],
            "form": ["10-Q", "10-K", "10-Q", "10-K/A", "4"],
            "reportDate": [
                "2026-04-26",
                "2026-01-25",
                "2025-10-26",
                "2004-01-25",
                "2024-10-27",
            ],
            "filingDate": [
                "2026-05-20",
                "2026-02-25",
                "2025-11-19",
                "2004-05-20",
                "2024-11-20",
            ],
        },
        "files": [{"name": "CIK0001045810-submissions-001.json"}],
    }
}


def test_only_periodic_forms_survive():
    out = parse_submissions(PAYLOAD)
    assert {f.form for f in out} == {"10-Q", "10-K", "10-K/A"}
    assert all(f.form != "4" for f in out), "ownership forms are not periodic reports"


def test_an_amendment_is_flagged():
    amended = [f for f in parse_submissions(PAYLOAD) if f.is_amendment]
    assert len(amended) == 1
    assert amended[0].form == "10-K/A"
    assert amended[0].report_date == date(2004, 1, 25)


def test_dates_are_parsed_not_strings():
    f = next(
        f for f in parse_submissions(PAYLOAD) if f.accession == "0001045810-26-000052"
    )
    assert f.report_date == date(2026, 4, 26)
    assert f.filing_date == date(2026, 5, 20)


def test_a_row_missing_its_report_date_is_dropped_not_guessed():
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["0001045810-26-000052"],
                "form": ["10-Q"],
                "reportDate": [""],
                "filingDate": ["2026-05-20"],
            }
        }
    }
    assert parse_submissions(payload) == []


def test_an_empty_payload_is_empty_not_an_error():
    assert parse_submissions({}) == []
    assert parse_submissions({"filings": {}}) == []
    assert parse_submissions(None) == []


def test_rows_are_hashable_and_deduplicate():
    out = parse_submissions(PAYLOAD)
    assert len(set(out)) == len(out)
    assert isinstance(out[0], SecFiling)


def test_archives_are_discovered_or_a_20_year_panel_becomes_3():
    """`filings.recent` is a window. Missing the archives is silent data loss."""
    assert archive_names(PAYLOAD) == ["CIK0001045810-submissions-001.json"]
    assert archive_names({}) == []
    assert archive_names({"filings": {"files": "not-a-list"}}) == []


def test_an_archive_document_is_the_bare_block():
    block = {
        "accessionNumber": ["0001045810-06-000001"],
        "form": ["10-K"],
        "reportDate": ["2006-01-29"],
        "filingDate": ["2006-03-28"],
    }
    out = parse_archive(block)
    assert len(out) == 1
    assert out[0].report_date == date(2006, 1, 29)


def test_ragged_parallel_arrays_do_not_misalign_rows():
    """A short array must truncate, never pair a form with a neighbour's date."""
    payload = {
        "filings": {
            "recent": {
                "accessionNumber": ["a", "b"],
                "form": ["10-Q", "10-K"],
                "reportDate": ["2026-04-26"],
                "filingDate": ["2026-05-20", "2026-02-25"],
            }
        }
    }
    out = parse_submissions(payload)
    assert len(out) == 1
    assert out[0].accession == "a"
