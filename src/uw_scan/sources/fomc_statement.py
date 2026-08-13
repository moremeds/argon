"""Official Federal Reserve FOMC statement source.

The matching official PDF is the stable primary artifact.  The accessible
HTML is retained separately and parsed strictly so publisher layout drift
cannot silently become an empty policy decision.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from typing import Final, Literal

import httpx

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.normalize import NormalizationError

from .fomc_release_contracts import (
    FomcReleaseCandidate,
    artifact_identity,
    bounded_release_error,
    require_official_response,
)
from .fomc_release_discovery import discover_official_release_candidates
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

logger = logging.getLogger(__name__)


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
    release_key: str
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
        release_key: str | None = None,
    ) -> "FomcStatementBundle":
        html = accessible_bytes.decode("utf-8", errors="replace")
        published_at = _infer_published_at(html, meeting_date)
        inferred_stem, inferred_date = artifact_identity(
            accessible_url,
            release_type="statement",
            media_type="html",
        )
        if inferred_date != meeting_date:
            raise ValueError("statement URL date does not match meeting_date")
        record_base = release_key or f"fomc-statement:{inferred_stem}"
        return cls(
            release_key=record_base,
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


@dataclass(frozen=True)
class FomcStatementFetchOutcome:
    candidate: FomcReleaseCandidate
    artifacts: tuple[MacroSourceArtifact, ...]
    bundle: FomcStatementBundle | None
    error_type: str | None = None
    error_message: str | None = None


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
        outcomes = self.fetch_outcomes(years=years, retrieved_at=retrieved_at)
        failures = [outcome for outcome in outcomes if outcome.bundle is None]
        if failures:
            first = failures[0]
            raise NormalizationError(
                "FOMC candidate fetch failed for "
                f"{first.candidate.release_key}: {first.error_message}"
            )
        return [outcome.bundle for outcome in outcomes if outcome.bundle is not None]

    def discover_candidates(
        self, *, years: tuple[int, ...]
    ) -> list[FomcReleaseCandidate]:
        return discover_official_release_candidates(
            get=self._get,
            base_url=self._base_url,
            calendar_path=self.CALENDAR_PATH,
            years=years,
            release_type="statement",
        )

    def fetch_outcomes(
        self,
        *,
        years: tuple[int, ...],
        retrieved_at: datetime | None = None,
    ) -> list[FomcStatementFetchOutcome]:
        candidates = self.discover_candidates(years=years)
        if not candidates:
            raise NormalizationError("FOMC discovery produced no statement candidates")
        observed_at = retrieved_at or datetime.now(UTC)
        return [
            self._fetch_candidate(candidate, retrieved_at=observed_at)
            for candidate in candidates
        ]

    def _fetch_candidate(
        self,
        candidate: FomcReleaseCandidate,
        *,
        retrieved_at: datetime,
    ) -> FomcStatementFetchOutcome:
        html_bytes: bytes | None = None
        pdf_bytes: bytes | None = None
        errors: list[tuple[str, str]] = []
        if candidate.discovery_error:
            errors.append(("ReleaseDiscoveryError", candidate.discovery_error))
        for media_type, url in (
            ("html", candidate.html_url),
            ("pdf", candidate.pdf_url),
        ):
            if url is None:
                continue
            try:
                response = self._get(url)
                require_official_response(
                    response,
                    discovery_url=candidate.discovery_url,
                    media_type=media_type,
                )
                if media_type == "html":
                    html_bytes = response.content
                else:
                    pdf_bytes = response.content
            except Exception as exc:
                logger.debug("statement candidate artifact fetch failed: %s", repr(exc))
                errors.append(bounded_release_error(exc))

        bundle: FomcStatementBundle | None = None
        if html_bytes is not None and pdf_bytes is not None:
            assert candidate.html_url is not None
            assert candidate.pdf_url is not None
            try:
                bundle = FomcStatementBundle.from_bytes(
                    release_key=candidate.release_key,
                    meeting_date=candidate.event_date,
                    accessible_url=candidate.html_url,
                    accessible_bytes=html_bytes,
                    pdf_url=candidate.pdf_url,
                    pdf_bytes=pdf_bytes,
                    retrieved_at=retrieved_at,
                )
            except Exception as exc:
                logger.debug("statement candidate bundle failed: %s", repr(exc))
                errors.append(bounded_release_error(exc))

        if bundle is not None:
            artifacts = (bundle.primary_artifact, bundle.accessible_artifact)
        else:
            published_at = (
                _infer_published_at(
                    html_bytes.decode("utf-8", errors="replace"),
                    candidate.event_date,
                )
                if html_bytes is not None
                else None
            )
            partial: list[MacroSourceArtifact] = []
            if pdf_bytes is not None and candidate.pdf_url is not None:
                partial.append(
                    _artifact(
                        source_record_id=f"{candidate.release_key}:pdf",
                        source_url=candidate.pdf_url,
                        media_type="application/pdf",
                        raw_bytes=pdf_bytes,
                        published_at=published_at,
                        retrieved_at=retrieved_at,
                    )
                )
            if html_bytes is not None and candidate.html_url is not None:
                partial.append(
                    _artifact(
                        source_record_id=f"{candidate.release_key}:html",
                        source_url=candidate.html_url,
                        media_type="text/html",
                        raw_bytes=html_bytes,
                        published_at=published_at,
                        retrieved_at=retrieved_at,
                    )
                )
            artifacts = tuple(partial)
        error_type = errors[0][0] if errors else None
        error_message = (
            "; ".join(message for _, message in errors)[:500] if errors else None
        )
        return FomcStatementFetchOutcome(
            candidate=candidate,
            artifacts=artifacts,
            bundle=bundle,
            error_type=error_type,
            error_message=error_message,
        )

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
        source_record_id=bundle.release_key,
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
