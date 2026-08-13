from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
import pytest

from uw_scan.sources.fomc_calendar import FomcCalendarProvider
from uw_scan.sources.fomc_text import _infer_action, _infer_target_range


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


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("0 to ¼ percent", (Decimal("0"), Decimal("0.25"))),
        ("3‑1/2 to 3‑3/4 percent", (Decimal("3.5"), Decimal("3.75"))),
        ("4–1/4 to 4–1/2 percent", (Decimal("4.25"), Decimal("4.5"))),
        (
            "The Committee decided to lower the target range for the federal "
            "funds rate by 1/2 percentage point, to 1 to 1-1/4 percent.",
            (Decimal("1"), Decimal("1.25")),
        ),
    ],
)
def test_target_range_normalizes_historical_numeric_notation(
    raw: str,
    expected: tuple[Decimal, Decimal],
) -> None:
    assert _infer_target_range(raw) == expected


@pytest.mark.parametrize("raw", ["1/0", "NaN", "Infinity", "3-1", "1//2", "3-1/2x"])
def test_numeric_token_rejects_malformed_or_nonfinite_values(raw: str) -> None:
    assert _infer_target_range(f"{raw} to 1 percent") is None


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        (
            "The Committee decided to keep the target range for the federal "
            "funds rate at 0 to 1/4 percent.",
            "Hold",
        ),
        (
            "The Committee decided to increase the target range for the federal "
            "funds rate to 5 to 5-1/4 percent.",
            "Hike",
        ),
        (
            "The Committee decided to lower the target range for the federal "
            "funds rate by 1/2 percentage point, to 1 to 1-1/4 percent.",
            "Cut",
        ),
    ],
)
def test_action_requires_explicit_committee_rate_decision(
    raw: str, expected: str
) -> None:
    assert _infer_action(raw) == expected


def test_action_does_not_classify_unrelated_raise_or_lower_language() -> None:
    assert (
        _infer_action(
            "One participant preferred to lower inflation, while staff expected "
            "businesses to raise wages."
        )
        is None
    )
