from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx

from uw_scan.sources.fomc_calendar import FomcCalendarProvider


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"


def _response(url: str, path: Path, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=path.read_bytes() if status_code == 200 else b"",
        request=httpx.Request("GET", url),
    )


def test_fomc_calendar_extracts_current_statement_and_projection_contracts() -> None:
    calendar_path = FIXTURES / "fomc_calendar_2026.html"
    statement_path = FIXTURES / "fomc_statement_2026_06.html"

    def fake_get(_provider: FomcCalendarProvider, path: str) -> httpx.Response:
        if path == FomcCalendarProvider.CALENDAR_PATH:
            return _response(path, calendar_path)
        if "20260617" in path and path.endswith("a.htm"):
            return _response(path, statement_path)
        return _response(path, statement_path, status_code=404)

    with patch.object(
        FomcCalendarProvider, "_get", autospec=True, side_effect=fake_get
    ):
        with FomcCalendarProvider() as provider:
            meetings = provider.fetch_meetings(years=(2026,))

    meeting = next(item for item in meetings if item.end_date == date(2026, 6, 17))
    assert meeting.start_date == date(2026, 6, 16)
    assert meeting.action == "Hold"
    assert meeting.vote_split == "12-0"
    assert meeting.target_range_lower == Decimal("3.5")
    assert meeting.target_range_upper == Decimal("3.75")
    assert meeting.published_at == datetime(
        2026, 6, 17, 14, tzinfo=ZoneInfo("America/New_York")
    )
    assert meeting.source_record_id == "fomc-statement:2026-06-17"
    assert meeting.source_url == (
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm"
    )
    assert meeting.statement_pdf_url == (
        "https://www.federalreserve.gov/monetarypolicy/files/monetary20260617a1.pdf"
    )
    assert meeting.projection_url == (
        "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260617.htm"
    )
    assert meeting.projection_pdf_url == (
        "https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20260617.pdf"
    )


def test_fomc_statement_without_decision_contract_remains_explicitly_missing() -> None:
    calendar = b"""
    <h4>2026 FOMC Meetings</h4><div>June</div><div>16-17*</div>
    <a href="/newsevents/pressreleases/monetary20260617a.htm">HTML</a>
    """
    statement = b"<html><body><p>No policy decision fields.</p></body></html>"
    responses = [
        httpx.Response(200, content=calendar, request=httpx.Request("GET", "/cal")),
        httpx.Response(200, content=statement, request=httpx.Request("GET", "/stmt")),
    ]
    with patch.object(FomcCalendarProvider, "_get", side_effect=responses):
        with FomcCalendarProvider() as provider:
            meeting = provider.fetch_meetings(years=(2026,))[0]

    assert meeting.action is None
    assert meeting.vote_split is None
    assert meeting.target_range_lower is None
    assert meeting.target_range_upper is None
    assert meeting.published_at is None
