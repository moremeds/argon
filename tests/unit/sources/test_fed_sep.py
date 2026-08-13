from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from bs4 import BeautifulSoup

from uw_scan.normalize import NormalizationError
from uw_scan.sources.fed_sep import FedSepProvider, SepSourceBundle, parse_sep_release
from uw_scan.sources.fomc_release_contracts import (
    FomcDiscoveryPageOutcome,
    FomcDiscoveryResult,
    FomcReleaseCandidate,
)


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
RETRIEVED_AT = datetime(2026, 8, 12, 12, 0, tzinfo=UTC)
HTML_URL = "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20260617.htm"
PDF_URL = "https://www.federalreserve.gov/monetarypolicy/files/fomcprojtabl20260617.pdf"


def _bundle(*, accessible_bytes: bytes | None = None) -> SepSourceBundle:
    return SepSourceBundle.from_bytes(
        meeting_date=date(2026, 6, 17),
        accessible_url=HTML_URL,
        accessible_bytes=(
            accessible_bytes
            if accessible_bytes is not None
            else (FIXTURES / "fed_sep_2026_06.html").read_bytes()
        ),
        pdf_url=PDF_URL,
        pdf_bytes=(FIXTURES / "fed_sep_2026_06.pdf").read_bytes(),
        retrieved_at=RETRIEVED_AT,
    )


def test_sep_parses_published_summary_and_anonymous_dot_distribution() -> None:
    bundle = _bundle()
    release = parse_sep_release(bundle)

    assert release.release_date == date(2026, 6, 17)
    assert release.meeting_date == date(2026, 6, 17)
    assert release.source_record_id == "fed-sep:fomcprojtabl20260617"
    assert release.published_at.isoformat() == "2026-06-17T14:00:00-04:00"
    assert release.source_url == PDF_URL
    assert release.accessible_source_url == HTML_URL

    policy_2026 = next(
        item
        for item in release.projections
        if item.variable == "federal_funds_rate" and item.horizon == "2026"
    )
    assert policy_2026.unit == "percent"
    assert policy_2026.median == Decimal("3.8")
    assert policy_2026.central_tendency == (Decimal("3.6"), Decimal("4.1"))
    assert policy_2026.range == (Decimal("3.4"), Decimal("4.4"))
    assert (
        sum(point.participant_count for point in policy_2026.participant_distribution)
        == 18
    )
    assert [
        (point.value, point.participant_count)
        for point in policy_2026.participant_distribution
    ] == [
        (Decimal("3.375"), 1),
        (Decimal("3.625"), 8),
        (Decimal("3.875"), 3),
        (Decimal("4.125"), 5),
        (Decimal("4.375"), 1),
    ]

    policy_2028 = next(
        item
        for item in release.projections
        if item.variable == "federal_funds_rate" and item.horizon == "2028"
    )
    assert (
        sum(point.participant_count for point in policy_2028.participant_distribution)
        == 17
    )


def test_sep_bundle_retains_stable_primary_pdf_and_exact_accessible_snapshot() -> None:
    bundle = _bundle()

    assert bundle.primary_artifact.source_record_id == (
        "fed-sep:fomcprojtabl20260617:pdf"
    )
    assert bundle.primary_artifact.content_hash == (
        "a517887623520922a782e0cd01fb38d4469bed951f63d2588efb99f72deddde3"
    )
    assert bundle.primary_artifact.content_length == 1_216_132
    assert bundle.primary_artifact.media_type == "application/pdf"
    assert (
        bundle.primary_artifact.available_at.isoformat() == "2026-06-17T14:00:00-04:00"
    )
    assert bundle.accessible_artifact.source_record_id == (
        "fed-sep:fomcprojtabl20260617:html"
    )
    assert bundle.accessible_artifact.content_hash == (
        "cb8e66750aa86de09773f127afb2bfd9e538c1152ee2b4344d73cc35ddec8b35"
    )
    assert bundle.accessible_artifact.content_length == 232_840


def test_sep_rejects_missing_required_tables() -> None:
    malformed = b"""
    <html><body>
      <p>For release at 2:00 p.m., EDT, June 17, 2026</p>
      <h4>Summary of Economic Projections</h4>
    </body></html>
    """
    with pytest.raises(NormalizationError, match="Table 1"):
        parse_sep_release(_bundle(accessible_bytes=malformed))


def test_sep_rejects_inconsistent_participant_totals() -> None:
    soup = BeautifulSoup(
        (FIXTURES / "fed_sep_2026_06.html").read_bytes(), "html.parser"
    )
    dot_table = soup.find_all("table")[5]
    row_3625 = next(
        row
        for row in dot_table.find_all("tr")
        if row.find(["th", "td"]).get_text(" ", strip=True) == "3.625"
    )
    row_3625.find_all(["th", "td"])[1].string = "7"

    with pytest.raises(NormalizationError, match="participant total"):
        parse_sep_release(_bundle(accessible_bytes=soup.encode("utf-8")))


def test_sep_discovers_exact_2020_golden_candidates_from_meeting_markers() -> None:
    calendar = (FIXTURES / "fomc_calendar_current.html").read_bytes()
    history = (FIXTURES / "fomc_historical_2020.html").read_bytes()

    def fake_get(_provider: FedSepProvider, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        if url.endswith("/monetarypolicy/fomccalendars.htm"):
            return httpx.Response(200, content=calendar, request=request)
        if url.endswith("/monetarypolicy/fomchistorical2020.htm"):
            return httpx.Response(200, content=history, request=request)
        if "fomcprojtabl2020" in url and url.endswith(".htm"):
            return httpx.Response(
                200,
                content=b"<html><title>Federal Reserve SEP</title></html>",
                headers={"content-type": "text/html"},
                request=request,
            )
        if "fomcprojtabl2020" in url and url.endswith(".pdf"):
            return httpx.Response(
                200,
                content=b"%PDF official SEP",
                headers={"content-type": "application/pdf"},
                request=request,
            )
        return httpx.Response(404, request=request)

    with patch.object(FedSepProvider, "_get", autospec=True, side_effect=fake_get):
        with FedSepProvider() as provider:
            candidates = provider.discover_candidates(years=(2020,))

    assert [item.release_key for item in candidates] == [
        "fed-sep:fomcprojtabl20200610",
        "fed-sep:fomcprojtabl20200916",
        "fed-sep:fomcprojtabl20201216",
    ]
    assert all(item.event_class is None for item in candidates)
    assert all(item.html_url and item.pdf_url for item in candidates)
    assert all(item.discovery_error is None for item in candidates)


def test_sep_outcomes_isolate_transport_failure_and_keep_partial_artifact() -> None:
    first = FomcReleaseCandidate(
        release_key="fed-sep:fomcprojtabl20200610",
        release_type="sep",
        event_date=date(2020, 6, 10),
        event_class=None,
        discovery_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
        ),
        html_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomcprojtabl20200610.htm"
        ),
        pdf_url=(
            "https://www.federalreserve.gov/monetarypolicy/files/"
            "fomcprojtabl20200610.pdf"
        ),
    )
    second = FomcReleaseCandidate(
        release_key="fed-sep:fomcprojtabl20260617",
        release_type="sep",
        event_date=date(2026, 6, 17),
        event_class=None,
        discovery_url=first.discovery_url,
        html_url=HTML_URL,
        pdf_url=PDF_URL,
    )

    def fake_get(_provider: FedSepProvider, url: str) -> httpx.Response:
        if url == first.pdf_url:
            raise httpx.ReadTimeout("first release PDF timed out")
        request = httpx.Request("GET", url)
        if url == first.html_url:
            return httpx.Response(
                200,
                content=b"<p>incomplete but exact</p>",
                headers={"content-type": "text/html"},
                request=request,
            )
        if url == second.html_url:
            return httpx.Response(
                200,
                content=(FIXTURES / "fed_sep_2026_06.html").read_bytes(),
                headers={"content-type": "text/html"},
                request=request,
            )
        return httpx.Response(
            200,
            content=(FIXTURES / "fed_sep_2026_06.pdf").read_bytes(),
            headers={"content-type": "application/pdf"},
            request=request,
        )

    with (
        patch.object(
            FedSepProvider,
            "discover_result",
            autospec=True,
            return_value=FomcDiscoveryResult(
                candidates=(first, second),
                page_outcomes=(),
                coverage_complete=True,
                missing_years=(),
            ),
        ),
        patch.object(FedSepProvider, "_get", autospec=True, side_effect=fake_get),
    ):
        with FedSepProvider() as provider:
            outcomes = provider.fetch_outcomes(
                years=(2020, 2026),
                retrieved_at=datetime(2026, 8, 13, tzinfo=UTC),
            )

    assert [outcome.candidate.release_key for outcome in outcomes] == [
        first.release_key,
        second.release_key,
    ]
    assert outcomes[0].bundle is None
    assert len(outcomes[0].artifacts) == 1
    assert outcomes[0].artifacts[0].raw_bytes == b"<p>incomplete but exact</p>"
    assert outcomes[0].error_type == "ReadTimeout"
    assert len(outcomes[0].error_message or "") <= 500
    assert outcomes[1].bundle is not None
    assert len(outcomes[1].artifacts) == 2


def test_sep_2022_html_alias_fetches_two_exact_artifacts_and_bundle() -> None:
    candidate = FomcReleaseCandidate(
        release_key="fed-sep:fomcprojtabl20220316",
        release_type="sep",
        event_date=date(2022, 3, 16),
        event_class=None,
        discovery_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomccalendars.htm"
        ),
        html_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomcprojtable20220316.htm"
        ),
        pdf_url=(
            "https://www.federalreserve.gov/monetarypolicy/files/"
            "fomcprojtabl20220316.pdf"
        ),
    )

    def fake_get(_provider: FedSepProvider, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        path = (
            FIXTURES / "fed_sep_2022_03.html"
            if url == candidate.html_url
            else FIXTURES / "fed_sep_2022_03.pdf"
        )
        return httpx.Response(
            200,
            content=path.read_bytes(),
            headers={
                "content-type": (
                    "text/html" if path.suffix == ".html" else "application/pdf"
                )
            },
            request=request,
        )

    result = FomcDiscoveryResult(
        candidates=(candidate,),
        page_outcomes=(
            FomcDiscoveryPageOutcome(
                year=None,
                url=candidate.discovery_url,
                role="current_calendar",
                status="ok",
            ),
        ),
        coverage_complete=True,
        missing_years=(),
    )
    with (
        patch.object(
            FedSepProvider, "discover_result", autospec=True, return_value=result
        ),
        patch.object(FedSepProvider, "_get", autospec=True, side_effect=fake_get),
    ):
        with FedSepProvider() as provider:
            outcomes = provider.fetch_outcomes(
                years=(2022,), retrieved_at=datetime(2026, 8, 13, tzinfo=UTC)
            )

    assert len(outcomes) == 1
    outcome = outcomes[0]
    assert outcome.candidate.release_key == "fed-sep:fomcprojtabl20220316"
    assert outcome.error_type is None
    assert outcome.bundle is not None
    assert outcome.bundle.release_key == "fed-sep:fomcprojtabl20220316"
    assert len(outcome.artifacts) == 2
    assert {artifact.content_length for artifact in outcome.artifacts} == {
        236_101,
        1_558_349,
    }


def test_sep_fetch_outcomes_rejects_incomplete_discovery_coverage() -> None:
    history_url = "https://www.federalreserve.gov/monetarypolicy/fomchistorical2024.htm"
    result = FomcDiscoveryResult(
        candidates=(),
        page_outcomes=(
            FomcDiscoveryPageOutcome(
                year=2024,
                url=history_url,
                role="historical_year",
                status="not_found",
                error_type="HTTPStatusError",
                error_message="404 Not Found",
            ),
        ),
        coverage_complete=False,
        missing_years=(2024,),
    )
    with patch.object(
        FedSepProvider, "discover_result", autospec=True, return_value=result
    ):
        with FedSepProvider() as provider:
            with pytest.raises(NormalizationError, match="incomplete.*2024"):
                provider.fetch_outcomes(years=(2024,))
