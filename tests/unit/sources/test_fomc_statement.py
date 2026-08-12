from __future__ import annotations

from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path

from uw_scan.sources.fomc_statement import FomcStatementBundle, parse_fomc_statement


FIXTURES = Path(__file__).parents[2] / "fixtures" / "macro"
HTML_URL = (
    "https://www.federalreserve.gov/newsevents/pressreleases/"
    "monetary20260617a.htm"
)
PDF_URL = (
    "https://www.federalreserve.gov/monetarypolicy/files/monetary20260617a1.pdf"
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
        "fomc-statement:2026-06-17:pdf"
    )
    assert release.action == "Hold"
    assert release.vote_split == "12-0"
    assert release.target_range_lower == Decimal("3.5")
    assert release.target_range_upper == Decimal("3.75")
    assert release.published_at.isoformat() == "2026-06-17T14:00:00-04:00"
    assert release.source_url == PDF_URL
    assert release.accessible_source_url == HTML_URL
