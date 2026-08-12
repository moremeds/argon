from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

import pytest
from bs4 import BeautifulSoup

from uw_scan.normalize import NormalizationError
from uw_scan.sources.fed_sep import SepSourceBundle, parse_sep_release


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
    assert release.source_record_id == "fed-sep:2026-06-17"
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

    assert bundle.primary_artifact.source_record_id == "fed-sep:2026-06-17:pdf"
    assert bundle.primary_artifact.content_hash == (
        "a517887623520922a782e0cd01fb38d4469bed951f63d2588efb99f72deddde3"
    )
    assert bundle.primary_artifact.content_length == 1_216_132
    assert bundle.primary_artifact.media_type == "application/pdf"
    assert (
        bundle.primary_artifact.available_at.isoformat() == "2026-06-17T14:00:00-04:00"
    )
    assert bundle.accessible_artifact.source_record_id == "fed-sep:2026-06-17:html"
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
