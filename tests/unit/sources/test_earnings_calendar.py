"""Pagination is the whole point: the busiest day observed returned 257 rows.

Sample rows are real UW `/api/earnings/premarket` payload shape, captured 2026-08-23.
"""

from __future__ import annotations

from datetime import date

from uw_scan.api.endpoints import EndpointSlug
from uw_scan.sources.earnings_calendar import PAGE_SIZE, fetch_calendar_symbols

REPORT_DATE = date(2026, 8, 21)

# A real row, trimmed to the fields the caller reads.
BEKE = {
    "symbol": "BEKE",
    "full_name": "KE HOLDINGS",
    "report_date": "2026-08-21",
    "report_time": "premarket",
    "sector": "Real Estate",
    "has_options": True,
}


class _Resp:
    def __init__(self, payload, status_code=200):
        self._payload = payload
        self.status_code = status_code

    def json(self):
        return self._payload


class _Client:
    """Serves a scripted page sequence per slot and records what was asked."""

    def __init__(self, pages: dict[EndpointSlug, list[list[dict]]], status=200):
        self._pages = pages
        self._status = status
        self.calls: list[tuple[EndpointSlug, int]] = []

    def get(self, slug, ticker=None, params=None, **_kw):
        page = int((params or {}).get("page", 0))
        self.calls.append((slug, page))
        seq = self._pages.get(slug, [])
        rows = seq[page] if page < len(seq) else []
        return _Resp({"data": rows}, self._status), {}


def _rows(n, prefix):
    return [dict(BEKE, symbol=f"{prefix}{i}") for i in range(n)]


def test_a_full_page_is_followed_by_the_next_one():
    pages = {
        EndpointSlug.EARNINGS_PREMARKET: [_rows(PAGE_SIZE, "P"), _rows(2, "Q")],
        EndpointSlug.EARNINGS_AFTERHOURS: [_rows(1, "A")],
    }
    client = _Client(pages)
    got = fetch_calendar_symbols(client, REPORT_DATE)

    assert "Q1" in got, "the second page was never read"
    assert len(got) == PAGE_SIZE + 2 + 1
    assert (EndpointSlug.EARNINGS_PREMARKET, 1) in client.calls


def test_a_short_page_stops_the_slot():
    pages = {EndpointSlug.EARNINGS_PREMARKET: [_rows(3, "P")]}
    client = _Client(pages)
    fetch_calendar_symbols(client, REPORT_DATE)
    premarket_pages = [p for s, p in client.calls if s == EndpointSlug.EARNINGS_PREMARKET]
    assert premarket_pages == [0]


def test_both_slots_are_asked():
    client = _Client({})
    fetch_calendar_symbols(client, REPORT_DATE)
    assert {s for s, _ in client.calls} == set(EndpointSlug) & {
        EndpointSlug.EARNINGS_PREMARKET,
        EndpointSlug.EARNINGS_AFTERHOURS,
    }


def test_the_page_budget_is_bounded():
    """A provider that never returns a short page must not loop forever."""
    client = _Client(
        {EndpointSlug.EARNINGS_PREMARKET: [_rows(PAGE_SIZE, f"P{p}_") for p in range(50)]}
    )
    fetch_calendar_symbols(client, REPORT_DATE, max_pages=3)
    premarket = [p for s, p in client.calls if s == EndpointSlug.EARNINGS_PREMARKET]
    assert premarket == [0, 1, 2]


def test_a_failing_slot_costs_only_that_slot():
    class _Boom(_Client):
        def get(self, slug, ticker=None, params=None, **_kw):
            if slug is EndpointSlug.EARNINGS_PREMARKET:
                raise RuntimeError("upstream down")
            return super().get(slug, ticker, params, **_kw)

    client = _Boom({EndpointSlug.EARNINGS_AFTERHOURS: [_rows(2, "A")]})
    got = fetch_calendar_symbols(client, REPORT_DATE)
    assert got == {"A0", "A1"}


def test_a_non_200_yields_no_symbols_and_does_not_raise():
    client = _Client({EndpointSlug.EARNINGS_PREMARKET: [_rows(5, "P")]}, status=429)
    assert fetch_calendar_symbols(client, REPORT_DATE) == set()


def test_symbols_are_normalised():
    client = _Client(
        {EndpointSlug.EARNINGS_PREMARKET: [[dict(BEKE, symbol=" beke ")]]}
    )
    assert fetch_calendar_symbols(client, REPORT_DATE) == {"BEKE"}
