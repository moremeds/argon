from __future__ import annotations

import hashlib
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from uw_scan.normalize import NormalizationError
from uw_scan.sources.fomc_statement import FomcStatementBundle, parse_fomc_statement
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
    assert bundle.primary_artifact.source_record_id == ("fomc-statement:2026-06-17:pdf")
    assert release.action == "Hold"
    assert release.vote_split == "12-0"
    assert release.target_range_lower == Decimal("3.5")
    assert release.target_range_upper == Decimal("3.75")
    assert release.published_at.isoformat() == "2026-06-17T14:00:00-04:00"
    assert release.source_url == PDF_URL
    assert release.accessible_source_url == HTML_URL


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
