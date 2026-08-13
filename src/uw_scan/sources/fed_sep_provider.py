"""Per-candidate acquisition for official Federal Reserve SEP releases."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, datetime

import httpx

from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.normalize import NormalizationError

from .fed_sep import SepSourceBundle, _artifact, _published_at
from .fomc_release_contracts import (
    FomcReleaseCandidate,
    bounded_release_error,
    require_official_response,
)
from .fomc_release_discovery import discover_official_release_candidates

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class SepFetchOutcome:
    candidate: FomcReleaseCandidate
    artifacts: tuple[MacroSourceArtifact, ...]
    bundle: SepSourceBundle | None
    error_type: str | None = None
    error_message: str | None = None


class FedSepProvider:
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

    def __enter__(self) -> FedSepProvider:
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
    ) -> list[SepSourceBundle]:
        outcomes = self.fetch_outcomes(years=years, retrieved_at=retrieved_at)
        failures = [outcome for outcome in outcomes if outcome.bundle is None]
        if failures:
            first = failures[0]
            raise NormalizationError(
                "SEP candidate fetch failed for "
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
            release_type="sep",
        )

    def fetch_outcomes(
        self,
        *,
        years: tuple[int, ...],
        retrieved_at: datetime | None = None,
    ) -> list[SepFetchOutcome]:
        candidates = self.discover_candidates(years=years)
        if not candidates:
            raise NormalizationError("FOMC discovery produced no SEP candidates")
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
    ) -> SepFetchOutcome:
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
                logger.debug("SEP candidate artifact fetch failed: %s", repr(exc))
                errors.append(bounded_release_error(exc))

        bundle: SepSourceBundle | None = None
        if html_bytes is not None and pdf_bytes is not None:
            assert candidate.html_url is not None
            assert candidate.pdf_url is not None
            try:
                bundle = SepSourceBundle.from_bytes(
                    release_key=candidate.release_key,
                    meeting_date=candidate.event_date,
                    accessible_url=candidate.html_url,
                    accessible_bytes=html_bytes,
                    pdf_url=candidate.pdf_url,
                    pdf_bytes=pdf_bytes,
                    retrieved_at=retrieved_at,
                )
            except Exception as exc:
                logger.debug("SEP candidate bundle failed: %s", repr(exc))
                errors.append(bounded_release_error(exc))

        artifacts = (
            (bundle.primary_artifact, bundle.accessible_artifact)
            if bundle is not None
            else self._partial_artifacts(
                candidate,
                html_bytes=html_bytes,
                pdf_bytes=pdf_bytes,
                retrieved_at=retrieved_at,
            )
        )
        error_type = errors[0][0] if errors else None
        error_message = (
            "; ".join(message for _, message in errors)[:500] if errors else None
        )
        return SepFetchOutcome(
            candidate=candidate,
            artifacts=artifacts,
            bundle=bundle,
            error_type=error_type,
            error_message=error_message,
        )

    @staticmethod
    def _partial_artifacts(
        candidate: FomcReleaseCandidate,
        *,
        html_bytes: bytes | None,
        pdf_bytes: bytes | None,
        retrieved_at: datetime,
    ) -> tuple[MacroSourceArtifact, ...]:
        published_at: datetime | None = None
        if html_bytes is not None:
            try:
                published_at = _published_at(
                    html_bytes, expected_date=candidate.event_date
                )
            except NormalizationError as exc:
                logger.debug(
                    "SEP partial artifact timestamp unavailable: %s", repr(exc)
                )
                published_at = None
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
        return tuple(partial)

    def _get(self, path_or_url: str) -> httpx.Response:
        url = (
            path_or_url
            if path_or_url.startswith("http")
            else f"{self._base_url}{path_or_url}"
        )
        return self._client.get(url)
