"""Official Federal Reserve FOMC statement source.

The matching official PDF is the stable primary artifact.  The accessible
HTML is retained separately and parsed strictly so publisher layout drift
cannot silently become an empty policy decision.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final, Literal

import httpx
from bs4 import BeautifulSoup

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.normalize import NormalizationError

from .fomc_calendar import (
    _statement_pdf_urls_by_date,
    _statement_urls_by_date,
)
from .fomc_text import (
    _infer_action,
    _infer_published_at,
    _infer_target_range,
    _infer_vote,
)

ARTIFACT_PARSER_VERSION: Final = "fomc_statement.v1"
SEMANTIC_PARSER_VERSION: Final = "fomc_statement.v2"
# Compatibility alias for callers that imported the original acquisition version.
PARSER_VERSION: Final = ARTIFACT_PARSER_VERSION
SOURCE: Final = "federal_reserve_fomc"


@dataclass(frozen=True)
class FomcStatementRelease:
    meeting_date: date
    published_at: datetime
    action: str
    vote_status: Literal["stated", "not_stated"]
    vote_split: str | None
    target_range_lower: Decimal
    target_range_upper: Decimal
    source_url: str
    accessible_source_url: str
    source_record_id: str
    parser_version: str


@dataclass(frozen=True)
class FomcStatementBundle:
    meeting_date: date
    primary_artifact: MacroSourceArtifact
    accessible_artifact: MacroSourceArtifact

    @classmethod
    def from_bytes(
        cls,
        *,
        meeting_date: date,
        accessible_url: str,
        accessible_bytes: bytes,
        pdf_url: str,
        pdf_bytes: bytes,
        retrieved_at: datetime,
    ) -> "FomcStatementBundle":
        html = accessible_bytes.decode("utf-8", errors="replace")
        published_at = _infer_published_at(html, meeting_date)
        record_base = f"fomc-statement:{meeting_date.isoformat()}"
        return cls(
            meeting_date=meeting_date,
            primary_artifact=_artifact(
                source_record_id=f"{record_base}:pdf",
                source_url=pdf_url,
                media_type="application/pdf",
                raw_bytes=pdf_bytes,
                published_at=published_at,
                retrieved_at=retrieved_at,
            ),
            accessible_artifact=_artifact(
                source_record_id=f"{record_base}:html",
                source_url=accessible_url,
                media_type="text/html",
                raw_bytes=accessible_bytes,
                published_at=published_at,
                retrieved_at=retrieved_at,
            ),
        )


class FomcStatementProvider:
    BASE_URL = "https://www.federalreserve.gov"
    CALENDAR_PATH = "/monetarypolicy/fomccalendars.htm"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_s: float = 30.0,
        trust_env: bool = False,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            trust_env=trust_env,
        )

    def __enter__(self) -> "FomcStatementProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_bundles(
        self,
        *,
        years: tuple[int, ...],
        retrieved_at: datetime | None = None,
    ) -> list[FomcStatementBundle]:
        calendar_response = self._get(self.CALENDAR_PATH)
        calendar_response.raise_for_status()
        soup = BeautifulSoup(calendar_response.content, "html.parser")
        html_urls = _statement_urls_by_date(soup, self._base_url)
        pdf_urls = _statement_pdf_urls_by_date(soup, self._base_url)
        wanted = set(years)
        meeting_dates = sorted(
            meeting_date
            for meeting_date in html_urls.keys() & pdf_urls.keys()
            if meeting_date.year in wanted
        )
        if not meeting_dates:
            raise NormalizationError(
                "FOMC calendar did not contain paired statement HTML/PDF links"
            )

        observed_at = retrieved_at or datetime.now(UTC)
        bundles: list[FomcStatementBundle] = []
        for meeting_date in meeting_dates:
            accessible_response = self._get(html_urls[meeting_date])
            accessible_response.raise_for_status()
            pdf_response = self._get(pdf_urls[meeting_date])
            pdf_response.raise_for_status()
            bundles.append(
                FomcStatementBundle.from_bytes(
                    meeting_date=meeting_date,
                    accessible_url=html_urls[meeting_date],
                    accessible_bytes=accessible_response.content,
                    pdf_url=pdf_urls[meeting_date],
                    pdf_bytes=pdf_response.content,
                    retrieved_at=observed_at,
                )
            )
        return bundles

    def _get(self, path_or_url: str) -> httpx.Response:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{self._base_url}{path_or_url}"
        )
        return self._client.get(url)


def parse_fomc_statement(bundle: FomcStatementBundle) -> FomcStatementRelease:
    raw = bundle.accessible_artifact.raw_bytes
    if raw is None:
        raise NormalizationError("FOMC accessible artifact is missing raw bytes")
    html = raw.decode("utf-8", errors="replace")
    action = _infer_action(html)
    vote = _infer_vote(html)
    vote_status = vote[0] if vote is not None else None
    vote_split = vote[1] if vote is not None else None
    target_range = _infer_target_range(html)
    published_at = _infer_published_at(html, bundle.meeting_date)
    missing = [
        label
        for label, value in (
            ("action", action),
            ("vote status", vote_status),
            ("target range", target_range),
            ("release timestamp", published_at),
        )
        if value is None
    ]
    if missing:
        raise NormalizationError(
            f"FOMC statement missing required fields: {', '.join(missing)}"
        )
    assert action is not None
    assert vote_status is not None
    assert target_range is not None
    assert published_at is not None
    return FomcStatementRelease(
        meeting_date=bundle.meeting_date,
        published_at=published_at,
        action=action,
        vote_status=vote_status,
        vote_split=vote_split,
        target_range_lower=target_range[0],
        target_range_upper=target_range[1],
        source_url=bundle.primary_artifact.source_url or "",
        accessible_source_url=bundle.accessible_artifact.source_url or "",
        source_record_id=f"fomc-statement:{bundle.meeting_date.isoformat()}",
        parser_version=SEMANTIC_PARSER_VERSION,
    )


def _artifact(
    *,
    source_record_id: str,
    source_url: str,
    media_type: str,
    raw_bytes: bytes,
    published_at: datetime | None,
    retrieved_at: datetime,
) -> MacroSourceArtifact:
    content_hash, content_length = macro_artifact_content_identity(raw_bytes=raw_bytes)
    available_at = published_at or retrieved_at
    return MacroSourceArtifact(
        source=SOURCE,
        source_kind="official",
        source_record_id=source_record_id,
        source_url=source_url,
        published_at=published_at,
        available_at=available_at,
        retrieved_at=retrieved_at,
        last_seen_at=retrieved_at,
        content_hash=content_hash,
        parser_version=ARTIFACT_PARSER_VERSION,
        quality_status="partial",
        cost_class="free_official",
        media_type=media_type,
        content_length=content_length,
        raw_bytes=raw_bytes,
    )
