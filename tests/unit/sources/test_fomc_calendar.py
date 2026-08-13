from __future__ import annotations

import hashlib
import json
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch
from zoneinfo import ZoneInfo

import httpx
import pytest

from uw_scan.sources.fomc_calendar import FomcCalendarProvider
from uw_scan.sources.fomc_release_contracts import (
    FomcReleaseCandidate,
    ReleaseDiscoveryError,
)
from uw_scan.sources.fomc_release_discovery import (
    discover_current_release_candidates,
    discover_official_release_candidates,
)
from uw_scan.sources.fomc_text import _infer_action, _infer_target_range


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
CURRENT_CALENDAR_URL = "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"


def _response(url: str, path: Path, *, status_code: int = 200) -> httpx.Response:
    return httpx.Response(
        status_code,
        content=path.read_bytes() if status_code == 200 else b"",
        request=httpx.Request("GET", url),
    )


@pytest.mark.parametrize(
    "fixture_name",
    ["fomc_calendar_current.html", "fomc_historical_2020.html"],
)
def test_frozen_official_discovery_fixture_matches_manifest(fixture_name: str) -> None:
    manifest = json.loads((FIXTURES / "manifest.json").read_text())
    metadata = next(
        item for item in manifest["artifacts"] if item["name"] == fixture_name
    )
    raw = (FIXTURES / fixture_name).read_bytes()

    assert metadata["url"].startswith("https://www.federalreserve.gov/")
    assert len(raw) == metadata["content_length"]
    assert hashlib.sha256(raw).hexdigest() == metadata["sha256"]


def test_release_candidate_enforces_statement_and_sep_event_class_invariants() -> None:
    with pytest.raises(ValueError, match="statement candidates require"):
        FomcReleaseCandidate(
            release_key="fomc-statement:monetary20200315a",
            release_type="statement",
            event_date=date(2020, 3, 15),
            event_class=None,
            discovery_url=(
                "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
            ),
            html_url=None,
            pdf_url=None,
        )

    with pytest.raises(ValueError, match="SEP candidates require"):
        FomcReleaseCandidate(
            release_key="fed-sep:fomcprojtabl20200610",
            release_type="sep",
            event_date=date(2020, 6, 10),
            event_class="scheduled_meeting",
            discovery_url=(
                "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
            ),
            html_url=None,
            pdf_url=None,
        )


def test_release_candidate_retains_incomplete_urls_but_rejects_identity_drift() -> None:
    incomplete = FomcReleaseCandidate(
        release_key="fomc-statement:monetary20200323a",
        release_type="statement",
        event_date=date(2020, 3, 23),
        event_class="notation_vote",
        discovery_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
        ),
        html_url=(
            "https://www.federalreserve.gov/newsevents/pressreleases/"
            "monetary20200323a.htm"
        ),
        pdf_url=None,
        discovery_error="missing PDF counterpart",
    )
    assert incomplete.pdf_url is None

    with pytest.raises(ValueError, match="does not match release key and date"):
        FomcReleaseCandidate(
            release_key="fomc-statement:monetary20200323a",
            release_type="statement",
            event_date=date(2020, 3, 23),
            event_class="notation_vote",
            discovery_url=incomplete.discovery_url,
            html_url=(
                "https://www.federalreserve.gov/newsevents/pressreleases/"
                "monetary20200315a.htm"
            ),
            pdf_url=None,
        )

    with pytest.raises(ValueError, match="configured Fed host"):
        FomcReleaseCandidate(
            release_key="fed-sep:fomcprojtabl20200610",
            release_type="sep",
            event_date=date(2020, 6, 10),
            event_class=None,
            discovery_url=incomplete.discovery_url,
            html_url=("https://evil.example/monetarypolicy/fomcprojtabl20200610.htm"),
            pdf_url=None,
        )


def test_current_discovery_uses_meeting_context_and_excludes_strategy_statement() -> (
    None
):
    candidates = discover_current_release_candidates(
        (FIXTURES / "fomc_calendar_current.html").read_bytes(),
        discovery_url=CURRENT_CALENDAR_URL,
        years=(2025,),
    )
    keys = {candidate.release_key for candidate in candidates}

    assert "fomc-statement:monetary20250822a" not in keys
    assert "fomc-statement:monetary20250730a" in keys


def test_current_discovery_retains_missing_counterparts_and_rejects_off_host() -> None:
    raw = b"""
    <div class="panel panel-default"><h4>2025 FOMC Meetings</h4>
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month"><strong>January</strong></div>
        <div class="fomc-meeting__date">28-29</div>
        <div><strong>Statement:</strong>
          <a href="/newsevents/pressreleases/monetary20250129a.htm">HTML</a>
        </div>
      </div>
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month"><strong>March</strong></div>
        <div class="fomc-meeting__date">18-19*</div>
        <div><strong>Statement:</strong>
          <a href="https://evil.example/monetary20250319a1.pdf">PDF</a>
          <a href="/newsevents/pressreleases/monetary20250319a.htm">HTML</a>
        </div>
      </div>
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month"><strong>June</strong></div>
        <div class="fomc-meeting__date">17-18*</div>
        <div><strong>Projection Materials</strong>
          <a href="/monetarypolicy/files/fomcprojtabl20250618.pdf">PDF</a>
        </div>
      </div>
    </div>
    """
    candidates = {
        candidate.release_key: candidate
        for candidate in discover_current_release_candidates(
            raw, discovery_url=CURRENT_CALENDAR_URL, years=(2025,)
        )
    }

    january = candidates["fomc-statement:monetary20250129a"]
    assert january.html_url is not None
    assert january.pdf_url is None
    assert "missing PDF" in (january.discovery_error or "")
    march = candidates["fomc-statement:monetary20250319a"]
    assert march.html_url is not None
    assert march.pdf_url is None
    assert "off-host" in (march.discovery_error or "")
    june = candidates["fed-sep:fomcprojtabl20250618"]
    assert june.html_url is None
    assert june.pdf_url is not None
    assert "missing HTML" in (june.discovery_error or "")


def test_current_discovery_deduplicates_exact_candidates_but_rejects_conflicts() -> (
    None
):
    meeting = b"""
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month"><strong>January</strong></div>
        <div class="fomc-meeting__date">28-29</div>
        <div><strong>Statement:</strong>
          <a href="/monetarypolicy/files/monetary20250129a1.pdf">PDF</a>
          <a href="/newsevents/pressreleases/monetary20250129a.htm">HTML</a>
        </div>
      </div>
    """
    exact = (
        b'<div class="panel panel-default"><h4>2025 FOMC Meetings</h4>'
        + meeting
        + meeting
        + b"</div>"
    )
    assert (
        len(
            discover_current_release_candidates(
                exact, discovery_url=CURRENT_CALENDAR_URL, years=(2025,)
            )
        )
        == 1
    )

    missing_pdf = meeting.replace(
        b'<a href="/monetarypolicy/files/monetary20250129a1.pdf">PDF</a>', b""
    )
    conflict = (
        b'<div class="panel panel-default"><h4>2025 FOMC Meetings</h4>'
        + meeting
        + missing_pdf
        + b"</div>"
    )
    with pytest.raises(ReleaseDiscoveryError, match="conflicting duplicate"):
        discover_current_release_candidates(
            conflict, discovery_url=CURRENT_CALENDAR_URL, years=(2025,)
        )


def test_official_discovery_does_not_request_history_for_current_covered_year() -> None:
    current = b"""
    <div class="panel panel-default"><h4>2025 FOMC Meetings</h4>
      <div class="row fomc-meeting">
        <div class="fomc-meeting__month"><strong>January</strong></div>
        <div class="fomc-meeting__date">28-29</div>
        <div><strong>Statement:</strong>
          <a href="/monetarypolicy/files/monetary20250129a1.pdf">PDF</a>
          <a href="/newsevents/pressreleases/monetary20250129a.htm">HTML</a>
        </div>
      </div>
    </div>
    """
    requested: list[str] = []

    def fake_get(url: str) -> httpx.Response:
        requested.append(url)
        if url == CURRENT_CALENDAR_URL:
            return httpx.Response(
                200,
                content=current,
                headers={"content-type": "text/html"},
                request=httpx.Request("GET", url),
            )
        raise AssertionError(f"unexpected historical request {url}")

    candidates = discover_official_release_candidates(
        get=fake_get,
        base_url="https://www.federalreserve.gov",
        calendar_path="/monetarypolicy/fomccalendars.htm",
        years=(2025,),
        release_type="statement",
    )

    assert [item.release_key for item in candidates] == [
        "fomc-statement:monetary20250129a"
    ]
    assert requested == [CURRENT_CALENDAR_URL]


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
    assert meeting.source_record_id == "fomc-statement:monetary20260617a"
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
