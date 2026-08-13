from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from unittest.mock import patch

import httpx
import pytest
from bs4 import BeautifulSoup

from uw_scan.normalize import NormalizationError
from uw_scan.sources.fomc_release_contracts import FomcReleaseCandidate
from uw_scan.sources.fomc_statement import (
    FomcStatementBundle,
    FomcStatementProvider,
    parse_fomc_statement,
)
from uw_scan.worker.jobs.macro_policy_jobs import _statement_observation


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
HTML_URL = (
    "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260617a.htm"
)
PDF_URL = "https://www.federalreserve.gov/monetarypolicy/files/monetary20260617a1.pdf"

HISTORICAL_RELEASES = [
    (
        "fomc_statement_2020_03_03.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200303a.htm",
        "f05f28d203777aa404d21a818afed1b6ee790e6edd8b2d24dcea6742a01104ff",
        date(2020, 3, 3),
        "Cut",
        Decimal("1"),
        Decimal("1.25"),
        "10-0",
        "2020-03-03T10:00:00-05:00",
    ),
    (
        "fomc_statement_2020_03_23.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200323a.htm",
        "9d79eb0ae897c4ac4cb9115636949cf8040e84584ba92c1ed9d0a1d2a3d42727",
        date(2020, 3, 23),
        "Hold",
        Decimal("0"),
        Decimal("0.25"),
        "10-0",
        "2020-03-23T08:00:00-04:00",
    ),
    (
        "fomc_statement_2020_09_16.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20200916a.htm",
        "4f44a30e8d21c1632c7718c7c3b0b51a048bbfbe492013a78e86981ec0c47fdc",
        date(2020, 9, 16),
        "Hold",
        Decimal("0"),
        Decimal("0.25"),
        "8-2",
        "2020-09-16T14:00:00-04:00",
    ),
    (
        "fomc_statement_2020_11_05.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20201105a.htm",
        "b6d8714bd4fa6d904dcde05fc8074a10dee5ed5b761521510c510f9fcb8b3158",
        date(2020, 11, 5),
        "Hold",
        Decimal("0"),
        Decimal("0.25"),
        "10-0",
        "2020-11-05T14:00:00-05:00",
    ),
    (
        "fomc_statement_2021_01.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20210127a.htm",
        "6ce332de5827e54b82d338013fada2116e86857a398c27aea9a0f759808743e9",
        date(2021, 1, 27),
        "Hold",
        Decimal("0"),
        Decimal("0.25"),
        "11-0",
        "2021-01-27T14:00:00-05:00",
    ),
    (
        "fomc_statement_2022_03.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20220316a.htm",
        "9fb545e687e2e6fb6ded2bbf69257257f05ad8d7ec141b9fc3836bca914863f6",
        date(2022, 3, 16),
        "Hike",
        Decimal("0.25"),
        Decimal("0.5"),
        "8-1",
        "2022-03-16T14:00:00-04:00",
    ),
    (
        "fomc_statement_2025_12_10.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20251210a.htm",
        "3ab349d951f0df5f2786ae5e00d7fbe602f06cb9d7bf8465e072774af0fc2026",
        date(2025, 12, 10),
        "Cut",
        Decimal("3.5"),
        Decimal("3.75"),
        "9-3",
        "2025-12-10T14:00:00-05:00",
    ),
    (
        "fomc_statement_2026_03.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260318a.htm",
        "4167d30e1fda3eab57cabfd8f01a6b58069717cd742cd57a843fcd2a597fd5f0",
        date(2026, 3, 18),
        "Hold",
        Decimal("3.5"),
        Decimal("3.75"),
        "11-1",
        "2026-03-18T14:00:00-04:00",
    ),
    (
        "fomc_statement_2026_04_29.html",
        "https://www.federalreserve.gov/newsevents/pressreleases/monetary20260429a.htm",
        "3d1a56f2096a58ba37400fccd6651c383720298544b65dd9bea02fcf99fa06ea",
        date(2026, 4, 29),
        "Hold",
        Decimal("3.5"),
        Decimal("3.75"),
        "8-4",
        "2026-04-29T14:00:00-04:00",
    ),
]
SOURCE_URL_BY_FIXTURE = {row[0]: row[1] for row in HISTORICAL_RELEASES}


def _bundle(
    *, meeting_date: date, accessible_url: str, accessible_bytes: bytes
) -> FomcStatementBundle:
    return FomcStatementBundle.from_bytes(
        meeting_date=meeting_date,
        accessible_url=accessible_url,
        accessible_bytes=accessible_bytes,
        pdf_url=PDF_URL,
        pdf_bytes=(FIXTURES / "fomc_statement_2026_06.pdf").read_bytes(),
        retrieved_at=datetime(2026, 8, 13, 12, tzinfo=UTC),
    )


def test_statement_bundle_retains_stable_pdf_and_parses_decision() -> None:
    bundle = FomcStatementBundle.from_bytes(
        meeting_date=date(2026, 6, 17),
        accessible_url=HTML_URL,
        accessible_bytes=(FIXTURES / "fomc_statement_2026_06.html").read_bytes(),
        pdf_url=PDF_URL,
        pdf_bytes=(FIXTURES / "fomc_statement_2026_06.pdf").read_bytes(),
        retrieved_at=datetime(2026, 6, 17, 18, 1, tzinfo=UTC),
    )
    release = parse_fomc_statement(bundle)

    assert bundle.primary_artifact.content_hash == (
        "13c6558e213dd433c4a0c255d5f7a25ab79992f672c9644994307afea5d7932f"
    )
    assert bundle.primary_artifact.content_length == 229_274
    assert bundle.primary_artifact.source_record_id == (
        "fomc-statement:monetary20260617a:pdf"
    )
    assert release.action == "Hold"
    assert release.vote_split == "12-0"
    assert release.target_range_lower == Decimal("3.5")
    assert release.target_range_upper == Decimal("3.75")
    assert release.published_at.isoformat() == "2026-06-17T14:00:00-04:00"
    assert release.source_url == PDF_URL
    assert release.accessible_source_url == HTML_URL
    assert release.source_record_id == "fomc-statement:monetary20260617a"


@pytest.mark.parametrize(
    (
        "fixture_name",
        "source_url",
        "expected_hash",
        "meeting_date",
        "action",
        "lower",
        "upper",
        "vote_split",
        "published_at",
    ),
    HISTORICAL_RELEASES,
)
def test_statement_parses_historical_official_format_families(
    fixture_name: str,
    source_url: str,
    expected_hash: str,
    meeting_date: date,
    action: str,
    lower: Decimal,
    upper: Decimal,
    vote_split: str,
    published_at: str,
) -> None:
    raw = (FIXTURES / fixture_name).read_bytes()
    assert hashlib.sha256(raw).hexdigest() == expected_hash

    release = parse_fomc_statement(
        _bundle(
            meeting_date=meeting_date,
            accessible_url=source_url,
            accessible_bytes=raw,
        )
    )

    assert release.action == action
    assert release.target_range_lower == lower
    assert release.target_range_upper == upper
    assert release.vote_status == "stated"
    assert release.vote_split == vote_split
    assert release.published_at.isoformat() == published_at


def test_notation_vote_rejects_malformed_named_voter() -> None:
    raw = (FIXTURES / "fomc_statement_2020_03_23.html").read_bytes()
    malformed = raw.replace(b"Michelle W. Bowman;", b"NOT A VALID VOTER 123;")
    assert malformed != raw

    with pytest.raises(NormalizationError, match="named voter"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2020, 3, 23),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2020_03_23.html"],
                accessible_bytes=malformed,
            )
        )


def test_regular_vote_rejects_unparsed_malformed_dissenter() -> None:
    raw = (FIXTURES / "fomc_statement_2026_03.html").read_bytes()
    malformed = raw.replace(
        b"Stephen I. Miran, who",
        b"Stephen I. Miran; NOT A VALID VOTER 123, who",
    )
    assert malformed != raw

    with pytest.raises(NormalizationError, match="named voter"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2026, 3, 18),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2026_03.html"],
                accessible_bytes=malformed,
            )
        )


def test_cross_paragraph_vote_rejects_malformed_dissenter() -> None:
    raw = (FIXTURES / "fomc_statement_2020_09_16.html").read_bytes()
    malformed = raw.replace(b"Robert S. Kaplan, who", b"NOT A VALID VOTER 123, who")
    assert malformed != raw

    with pytest.raises(NormalizationError, match="named voter"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2020, 9, 16),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2020_09_16.html"],
                accessible_bytes=malformed,
            )
        )


def test_cross_paragraph_vote_rejects_noncontiguous_against_block() -> None:
    raw = (FIXTURES / "fomc_statement_2020_09_16.html").read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    against = next(
        paragraph
        for paragraph in soup.find_all("p")
        if paragraph.get_text(" ", strip=True).startswith("Voting against the action")
    )
    intervening = soup.new_tag("p")
    intervening.string = "Unrelated intervening paragraph."
    against.insert_before(intervening)
    malformed = soup.encode("utf-8")

    with pytest.raises(NormalizationError, match="noncontiguous voting-against"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2020, 9, 16),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2020_09_16.html"],
                accessible_bytes=malformed,
            )
        )


def test_statement_rejects_second_conflicting_policy_decision() -> None:
    raw = (FIXTURES / "fomc_statement_2026_03.html").read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    policy_decision = next(
        paragraph
        for paragraph in soup.find_all("p")
        if "decided to maintain the target range for the federal funds rate"
        in paragraph.get_text(" ", strip=True)
    )
    conflicting = soup.new_tag("p")
    conflicting.string = (
        "The Committee decided to raise the target range for the federal funds "
        "rate to 4 to 4-1/4 percent."
    )
    policy_decision.insert_after(conflicting)

    with pytest.raises(NormalizationError, match="multiple policy decisions"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2026, 3, 18),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2026_03.html"],
                accessible_bytes=soup.encode("utf-8"),
            )
        )


def test_statement_rejects_second_monetary_policy_vote_block() -> None:
    raw = (FIXTURES / "fomc_statement_2026_03.html").read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    voting_for = next(
        paragraph
        for paragraph in soup.find_all("p")
        if paragraph.get_text(" ", strip=True).startswith(
            "Voting for the monetary policy action were"
        )
    )
    voting_for.insert_after(BeautifulSoup(str(voting_for), "html.parser").p)

    with pytest.raises(NormalizationError, match="multiple monetary-policy votes"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2026, 3, 18),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2026_03.html"],
                accessible_bytes=soup.encode("utf-8"),
            )
        )


def test_statement_rejects_second_vote_clause_in_same_paragraph() -> None:
    raw = (FIXTURES / "fomc_statement_2026_03.html").read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    voting_for = next(
        paragraph
        for paragraph in soup.find_all("p")
        if paragraph.get_text(" ", strip=True).startswith(
            "Voting for the monetary policy action were"
        )
    )
    duplicate_text = voting_for.get_text(" ", strip=True)
    voting_for.append(f" {duplicate_text}")

    with pytest.raises(NormalizationError, match="multiple monetary-policy votes"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2026, 3, 18),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2026_03.html"],
                accessible_bytes=soup.encode("utf-8"),
            )
        )


@pytest.mark.parametrize(
    (
        "fixture_name",
        "meeting_date",
        "for_name",
        "against_name",
        "duplicated_against_name",
    ),
    [
        (
            "fomc_statement_2026_03.html",
            date(2026, 3, 18),
            b"Jerome H. Powell, Chair;",
            b"Stephen I. Miran, who",
            b"Jerome H. Powell, who",
        ),
        (
            "fomc_statement_2020_09_16.html",
            date(2020, 9, 16),
            b"Michelle W. Bowman;",
            b"Robert S. Kaplan, who",
            b"Michelle W. Bowman, who",
        ),
    ],
)
def test_regular_vote_rejects_voter_on_both_sides(
    fixture_name: str,
    meeting_date: date,
    for_name: bytes,
    against_name: bytes,
    duplicated_against_name: bytes,
) -> None:
    raw = (FIXTURES / fixture_name).read_bytes()
    assert for_name in raw
    duplicated = raw.replace(against_name, duplicated_against_name)
    assert duplicated != raw

    with pytest.raises(NormalizationError, match="both sides"):
        parse_fomc_statement(
            _bundle(
                meeting_date=meeting_date,
                accessible_url=SOURCE_URL_BY_FIXTURE[fixture_name],
                accessible_bytes=duplicated,
            )
        )


@pytest.mark.parametrize(
    ("fixture_name", "meeting_date", "original", "canonical_duplicate"),
    [
        (
            "fomc_statement_2026_03.html",
            date(2026, 3, 18),
            b"Michael S. Barr;",
            b"Jerome H. Powell;",
        ),
        (
            "fomc_statement_2025_12_10.html",
            date(2025, 12, 10),
            b"and Austan D. Goolsbee and Jeffrey R. Schmid, who preferred no change",
            b"and Stephen I. Miran, Chair, who preferred no change",
        ),
    ],
)
def test_regular_vote_rejects_same_side_canonical_duplicate(
    fixture_name: str,
    meeting_date: date,
    original: bytes,
    canonical_duplicate: bytes,
) -> None:
    raw = (FIXTURES / fixture_name).read_bytes()
    duplicated = raw.replace(original, canonical_duplicate)
    assert duplicated != raw

    with pytest.raises(NormalizationError, match="duplicate named voter"):
        parse_fomc_statement(
            _bundle(
                meeting_date=meeting_date,
                accessible_url=SOURCE_URL_BY_FIXTURE[fixture_name],
                accessible_bytes=duplicated,
            )
        )


@pytest.mark.parametrize(
    "malformed_names",
    [
        b"Beth M. Hammack, and, Lorie K. Logan",
        b"Beth M. Hammack,, Neel Kashkari, and Lorie K. Logan",
    ],
)
def test_regular_vote_rejects_malformed_comma_separated_dissenters(
    malformed_names: bytes,
) -> None:
    raw = (FIXTURES / "fomc_statement_2026_04_29.html").read_bytes()
    malformed = raw.replace(
        b"Beth M. Hammack, Neel Kashkari, and Lorie K. Logan",
        malformed_names,
    )
    assert malformed != raw

    with pytest.raises(NormalizationError, match="named voter"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2026, 4, 29),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2026_04_29.html"],
                accessible_bytes=malformed,
            )
        )


def test_notation_vote_does_not_fall_through_to_operational_unanimous_vote() -> None:
    raw = (FIXTURES / "fomc_statement_2020_03_23.html").read_bytes()
    soup = BeautifulSoup(raw, "html.parser")
    monetary_vote = next(
        paragraph
        for paragraph in soup.find_all("p")
        if "Voting (by notation) for the monetary policy action were"
        in paragraph.get_text(" ", strip=True)
    )
    monetary_vote.decompose()
    mutated = soup.encode("utf-8")
    assert b"voted unanimously to authorize and direct" in mutated
    assert b"Voting (by notation) for the monetary policy action" not in mutated

    with pytest.raises(NormalizationError, match="vote status"):
        parse_fomc_statement(
            _bundle(
                meeting_date=date(2020, 3, 23),
                accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2020_03_23.html"],
                accessible_bytes=mutated,
            )
        )


def test_statement_keeps_artifact_and_semantic_parser_versions_separate() -> None:
    bundle = _bundle(
        meeting_date=date(2026, 3, 18),
        accessible_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2026_03.html"],
        accessible_bytes=(FIXTURES / "fomc_statement_2026_03.html").read_bytes(),
    )
    release = parse_fomc_statement(bundle)
    row = _statement_observation(release, 7, bundle.accessible_artifact)

    assert bundle.accessible_artifact.parser_version == "fomc_statement.v1"
    assert release.parser_version == "fomc_statement.v2"
    assert row["parser_version"] == "fomc_statement.v2"
    assert row["value_json"]["parser_version"] == "fomc_statement.v2"
    assert row["value_json"]["points"][0]["vote_status"] == "stated"


def test_statement_discovers_exact_2020_golden_candidates() -> None:
    calendar = (FIXTURES / "fomc_calendar_current.html").read_bytes()
    history = (FIXTURES / "fomc_historical_2020.html").read_bytes()

    def fake_get(_provider: FomcStatementProvider, url: str) -> httpx.Response:
        request = httpx.Request("GET", url)
        if url.endswith("/monetarypolicy/fomccalendars.htm"):
            return httpx.Response(200, content=calendar, request=request)
        if url.endswith("/monetarypolicy/fomchistorical2020.htm"):
            return httpx.Response(200, content=history, request=request)
        if url.endswith("/newsevents/pressreleases/monetary20200323a.htm"):
            return httpx.Response(
                200,
                content=(FIXTURES / "fomc_statement_2020_03_23.html").read_bytes(),
                headers={"content-type": "text/html"},
                request=request,
            )
        if url.endswith("a.htm"):
            stem = url.rsplit("/", 1)[-1].removesuffix(".htm")
            body = (f'<a href="/monetarypolicy/files/{stem}1.pdf">PDF</a>').encode()
            return httpx.Response(
                200,
                content=body,
                headers={"content-type": "text/html"},
                request=request,
            )
        if url.endswith(".pdf"):
            return httpx.Response(
                200,
                content=b"%PDF official",
                headers={"content-type": "application/pdf"},
                request=request,
            )
        return httpx.Response(404, request=request)

    with patch.object(
        FomcStatementProvider, "_get", autospec=True, side_effect=fake_get
    ):
        with FomcStatementProvider() as provider:
            candidates = provider.discover_candidates(years=(2020,))

    expected_classes = {
        "fomc-statement:monetary20200129a": "scheduled_meeting",
        "fomc-statement:monetary20200303a": "unscheduled_meeting",
        "fomc-statement:monetary20200315a": "unscheduled_meeting",
        "fomc-statement:monetary20200323a": "notation_vote",
        "fomc-statement:monetary20200429a": "scheduled_meeting",
        "fomc-statement:monetary20200610a": "scheduled_meeting",
        "fomc-statement:monetary20200729a": "scheduled_meeting",
        "fomc-statement:monetary20200916a": "scheduled_meeting",
        "fomc-statement:monetary20201105a": "scheduled_meeting",
        "fomc-statement:monetary20201216a": "scheduled_meeting",
    }
    assert [item.release_key for item in candidates] == sorted(expected_classes)
    assert {item.release_key: item.event_class for item in candidates} == (
        expected_classes
    )
    assert all(item.html_url and item.pdf_url for item in candidates)
    assert all(item.discovery_error is None for item in candidates)
    march_23 = next(
        item
        for item in candidates
        if item.release_key == "fomc-statement:monetary20200323a"
    )
    assert march_23.pdf_url == (
        "https://www.federalreserve.gov/newsevents/pressreleases/files/"
        "monetary20200323a1.pdf"
    )


def test_statement_outcomes_isolate_transport_failure_and_keep_partial_artifact() -> (
    None
):
    first = FomcReleaseCandidate(
        release_key="fomc-statement:monetary20200129a",
        release_type="statement",
        event_date=date(2020, 1, 29),
        event_class="scheduled_meeting",
        discovery_url=(
            "https://www.federalreserve.gov/monetarypolicy/fomchistorical2020.htm"
        ),
        html_url=(
            "https://www.federalreserve.gov/newsevents/pressreleases/"
            "monetary20200129a.htm"
        ),
        pdf_url=(
            "https://www.federalreserve.gov/monetarypolicy/files/monetary20200129a1.pdf"
        ),
    )
    second = FomcReleaseCandidate(
        release_key="fomc-statement:monetary20200303a",
        release_type="statement",
        event_date=date(2020, 3, 3),
        event_class="unscheduled_meeting",
        discovery_url=first.discovery_url,
        html_url=SOURCE_URL_BY_FIXTURE["fomc_statement_2020_03_03.html"],
        pdf_url=(
            "https://www.federalreserve.gov/monetarypolicy/files/monetary20200303a1.pdf"
        ),
    )

    def fake_get(_provider: FomcStatementProvider, url: str) -> httpx.Response:
        if url == first.html_url:
            raise httpx.ConnectError("first release unavailable")
        request = httpx.Request("GET", url)
        if url == second.html_url:
            return httpx.Response(
                200,
                content=(FIXTURES / "fomc_statement_2020_03_03.html").read_bytes(),
                headers={"content-type": "text/html"},
                request=request,
            )
        return httpx.Response(
            200,
            content=b"%PDF exact bytes",
            headers={"content-type": "application/pdf"},
            request=request,
        )

    with (
        patch.object(
            FomcStatementProvider,
            "discover_candidates",
            autospec=True,
            return_value=[first, second],
        ),
        patch.object(
            FomcStatementProvider, "_get", autospec=True, side_effect=fake_get
        ),
    ):
        with FomcStatementProvider() as provider:
            outcomes = provider.fetch_outcomes(
                years=(2020,), retrieved_at=datetime(2026, 8, 13, tzinfo=UTC)
            )

    assert [outcome.candidate.release_key for outcome in outcomes] == [
        first.release_key,
        second.release_key,
    ]
    assert outcomes[0].bundle is None
    assert len(outcomes[0].artifacts) == 1
    assert outcomes[0].artifacts[0].raw_bytes == b"%PDF exact bytes"
    assert outcomes[0].error_type == "ConnectError"
    assert len(outcomes[0].error_message or "") <= 500
    assert outcomes[1].bundle is not None
    assert len(outcomes[1].artifacts) == 2
