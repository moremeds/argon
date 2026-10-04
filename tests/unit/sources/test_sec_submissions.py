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


# --- fetch path: the status contract (I-15/I-17) -----------------------------

import httpx  # noqa: E402
import pytest  # noqa: E402

from uw_scan.sources.sec_submissions import (  # noqa: E402
    fetch_cik_map,
    fetch_filings,
)
from uw_scan.sources.source_errors import SourceUnavailable  # noqa: E402

# NVDA's real CIK; the archive file name below is a labeled stand-in.
_NVDA_CIK = "0001045810"
_ARCHIVE = "CIK0001045810-submissions-001.json"


def _client(routes):
    """routes: url path -> httpx.Response | callable(request)."""

    def handler(request: httpx.Request) -> httpx.Response:
        r = routes[request.url.path]
        return r(request) if callable(r) else r

    return httpx.Client(transport=httpx.MockTransport(handler))


def _with_archive(payload):
    out = {**payload, "filings": {**payload["filings"], "files": [{"name": _ARCHIVE}]}}
    return out


def test_cik_map_pads_and_skips_a_malformed_entry():
    routes = {
        "/files/company_tickers.json": httpx.Response(
            200,
            json={
                "0": {"cik_str": 1045810, "ticker": "NVDA", "title": "NVIDIA"},
                "1": {"cik_str": "not-a-number", "ticker": "BAD", "title": "x"},
            },
        )
    }
    assert fetch_cik_map(_client(routes)) == {"NVDA": _NVDA_CIK}


@pytest.mark.parametrize(
    "resp",
    [
        httpx.Response(503, text="busy"),
        httpx.Response(200, text="<html>throttled</html>"),
        httpx.Response(200, json=["not", "an", "object"]),
    ],
)
def test_cik_map_failure_raises(resp):
    with pytest.raises(SourceUnavailable):
        fetch_cik_map(_client({"/files/company_tickers.json": resp}))


def test_filings_include_archive_pages():
    routes = {
        f"/submissions/CIK{_NVDA_CIK}.json": httpx.Response(
            200, json=_with_archive(PAYLOAD)
        ),
        f"/submissions/{_ARCHIVE}": httpx.Response(
            200, json=PAYLOAD["filings"]["recent"]
        ),
    }
    filings = fetch_filings(_client(routes), _NVDA_CIK)
    assert filings == sorted(
        set(parse_submissions(PAYLOAD)),
        key=lambda f: (f.report_date, f.filing_date, f.accession),
    )
    assert filings  # non-vacuity


def test_submissions_failure_raises():
    routes = {f"/submissions/CIK{_NVDA_CIK}.json": httpx.Response(404, json={})}
    with pytest.raises(SourceUnavailable, match="404"):
        fetch_filings(_client(routes), _NVDA_CIK)


def test_a_failed_archive_page_raises_rather_than_under_reporting():
    """It used to be skipped silently, returning an issuer's filings minus
    everything on that archive page."""
    routes = {
        f"/submissions/CIK{_NVDA_CIK}.json": httpx.Response(
            200, json=_with_archive(PAYLOAD)
        ),
        f"/submissions/{_ARCHIVE}": httpx.Response(500, text="oops"),
    }
    with pytest.raises(SourceUnavailable, match="500"):
        fetch_filings(_client(routes), _NVDA_CIK)


def test_programming_error_propagates():
    def boom(request):
        raise TypeError("bad handler")

    with pytest.raises(TypeError, match="bad handler"):
        fetch_filings(_client({f"/submissions/CIK{_NVDA_CIK}.json": boom}), _NVDA_CIK)
