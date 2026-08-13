"""Typed discovery of official Federal Reserve statement and SEP releases."""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date
from typing import Literal
from urllib.parse import urljoin

import httpx
from bs4 import BeautifulSoup

from .fomc_release_contracts import (
    MAX_ERROR_LENGTH,
    FomcDiscoveryPageOutcome,
    FomcDiscoveryResult,
    FomcReleaseCandidate,
    ReleaseDiscoveryError,
    ReleaseType,
    artifact_identity,
    bounded_messages,
    bounded_release_error,
    deduplicate_release_candidates,
    require_official_response,
    url_origin,
)
from .fomc_release_census import (
    census_current_release_anchors,
    census_historical_release_anchors,
    reconcile_anchor_census,
)
from .fomc_release_dom import (
    discover_current_release_candidates,
    inventory_current_release_page,
    inventory_historical_release_page,
)

__all__ = [
    "discover_current_release_candidates",
    "discover_official_release_candidates",
    "discover_official_release_result",
]

logger = logging.getLogger(__name__)


def discover_official_release_candidates(
    *,
    get: Callable[[str], httpx.Response],
    base_url: str,
    calendar_path: str,
    years: Iterable[int],
    release_type: ReleaseType,
    as_of_date: date | None = None,
) -> list[FomcReleaseCandidate]:
    """Compatibility projection of the audited official discovery result."""

    return list(
        discover_official_release_result(
            get=get,
            base_url=base_url,
            calendar_path=calendar_path,
            years=years,
            release_type=release_type,
            as_of_date=as_of_date or date.today(),
        ).candidates
    )


def discover_official_release_result(
    *,
    get: Callable[[str], httpx.Response],
    base_url: str,
    calendar_path: str,
    years: Iterable[int],
    release_type: ReleaseType,
    as_of_date: date,
) -> FomcDiscoveryResult:
    """Discover candidates and explicitly audit every bounded index request."""

    requested_years = tuple(sorted(set(years)))
    calendar_url = urljoin(f"{base_url.rstrip('/')}/", calendar_path.lstrip("/"))
    page_outcomes: list[FomcDiscoveryPageOutcome] = []
    candidates: list[FomcReleaseCandidate] = []
    try:
        calendar_response = get(calendar_url)
        require_official_response(
            calendar_response, discovery_url=calendar_url, media_type="html"
        )
    except Exception as exc:
        page_outcomes.append(
            _page_failure_outcome(
                exc,
                year=None,
                url=calendar_url,
                role="current_calendar",
            )
        )
    else:
        try:
            current_inventory = inventory_current_release_page(
                calendar_response.content,
                discovery_url=calendar_url,
                years=requested_years,
                release_type=release_type,
                as_of_date=as_of_date,
            )
        except ReleaseDiscoveryError:
            raise
        except Exception as exc:
            page_outcomes.append(
                _page_failure_outcome(
                    exc,
                    year=None,
                    url=calendar_url,
                    role="current_calendar",
                )
            )
        else:
            current_slots = reconcile_anchor_census(
                current_inventory.slots,
                census_current_release_anchors(
                    calendar_response.content,
                    discovery_url=calendar_url,
                    years=requested_years,
                    release_type=release_type,
                    as_of_date=as_of_date,
                ),
            )
            page_outcomes.append(
                FomcDiscoveryPageOutcome(
                    year=None,
                    url=calendar_url,
                    role="current_calendar",
                    status="ok",
                    slot_outcomes=current_slots,
                )
            )
            candidates.extend(current_inventory.candidates)

    for year in requested_years:
        if year >= as_of_date.year:
            continue
        history_url = urljoin(
            f"{base_url.rstrip('/')}/",
            f"monetarypolicy/fomchistorical{year}.htm",
        )
        try:
            response = get(history_url)
            require_official_response(
                response, discovery_url=history_url, media_type="html"
            )
        except Exception as exc:
            page_outcomes.append(
                _page_failure_outcome(
                    exc,
                    year=year,
                    url=history_url,
                    role="historical_year",
                )
            )
            continue
        try:
            historical_inventory = inventory_historical_release_page(
                response.content,
                discovery_url=history_url,
                year=year,
                release_type=release_type,
            )
        except ReleaseDiscoveryError:
            raise
        except Exception as exc:
            page_outcomes.append(
                _page_failure_outcome(
                    exc,
                    year=year,
                    url=history_url,
                    role="historical_year",
                )
            )
            continue
        historical_slots = reconcile_anchor_census(
            historical_inventory.slots,
            census_historical_release_anchors(
                response.content,
                discovery_url=history_url,
                year=year,
                release_type=release_type,
            ),
        )
        page_outcomes.append(
            FomcDiscoveryPageOutcome(
                year=year,
                url=history_url,
                role="historical_year",
                status="ok",
                slot_outcomes=historical_slots,
            )
        )
        for candidate in historical_inventory.candidates:
            if release_type == "statement":
                candidates.append(_complete_historical_statement(candidate, get=get))
            else:
                candidates.append(_validate_historical_sep(candidate, get=get))
    deduplicated = deduplicate_release_candidates(candidates)
    accepted_identities = {
        slot.identity
        for page in page_outcomes
        for slot in page.slot_outcomes
        if slot.status == "accepted"
    }
    unresolved = [
        slot
        for page in page_outcomes
        for slot in page.slot_outcomes
        if slot.status == "rejected"
        and (slot.identity is None or slot.identity not in accepted_identities)
    ]
    covered_years = {
        slot.year
        for page in page_outcomes
        for slot in page.slot_outcomes
        if slot.status == "accepted"
    }
    unresolved_years = {slot.year for slot in unresolved}
    missing_years = tuple(
        year
        for year in requested_years
        if year not in covered_years or year in unresolved_years
    )
    return FomcDiscoveryResult(
        candidates=tuple(deduplicated),
        page_outcomes=tuple(page_outcomes),
        coverage_complete=not missing_years,
        missing_years=missing_years,
    )


def _page_failure_outcome(
    exc: BaseException,
    *,
    year: int | None,
    url: str,
    role: Literal["current_calendar", "historical_year"],
) -> FomcDiscoveryPageOutcome:
    error_type, error_message = bounded_release_error(exc)
    status: Literal["not_found", "error"] = "error"
    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 404:
        status = "not_found"
    return FomcDiscoveryPageOutcome(
        year=year,
        url=url,
        role=role,
        status=status,
        error_type=error_type,
        error_message=error_message,
    )


def _complete_historical_statement(
    candidate: FomcReleaseCandidate,
    *,
    get: Callable[[str], httpx.Response],
) -> FomcReleaseCandidate:
    assert candidate.html_url is not None
    try:
        response = get(candidate.html_url)
        require_official_response(
            response,
            discovery_url=candidate.discovery_url,
            media_type="html",
        )
        soup = BeautifulSoup(response.content, "html.parser")
        pdf_urls: list[str] = []
        for link in soup.find_all("a", href=True):
            if _label(link.get_text(" ", strip=True)) != "PDF":
                continue
            url = urljoin(candidate.html_url, str(link["href"]))
            if url_origin(url) != url_origin(candidate.discovery_url):
                continue
            try:
                stem, event_date = artifact_identity(
                    url, release_type="statement", media_type="pdf"
                )
            except ValueError as exc:
                logger.debug("rejecting unrelated statement PDF URL: %s", repr(exc))
                continue
            if (
                candidate.release_key == f"fomc-statement:{stem}"
                and candidate.event_date == event_date
            ):
                pdf_urls.append(url)
        if len(set(pdf_urls)) != 1:
            raise ReleaseDiscoveryError(
                "statement page did not expose one same-release official PDF"
            )
        pdf_url = pdf_urls[0]
        pdf_response = get(pdf_url)
        require_official_response(
            pdf_response,
            discovery_url=candidate.discovery_url,
            media_type="pdf",
        )
        return replace(candidate, pdf_url=pdf_url, discovery_error=None)
    except Exception as exc:
        logger.debug("historical statement completion failed: %s", repr(exc))
        error_type, message = bounded_release_error(exc)
        keep_pdf = (
            locals().get("pdf_url") if _is_transient_validation_error(exc) else None
        )
        return replace(
            candidate,
            pdf_url=keep_pdf,
            discovery_error=f"{error_type}: {message}"[:MAX_ERROR_LENGTH],
        )


def _validate_historical_sep(
    candidate: FomcReleaseCandidate,
    *,
    get: Callable[[str], httpx.Response],
) -> FomcReleaseCandidate:
    errors: list[str] = []
    retained = {"html": candidate.html_url, "pdf": candidate.pdf_url}
    for media_type, url in (("html", candidate.html_url), ("pdf", candidate.pdf_url)):
        assert url is not None
        try:
            response = get(url)
            require_official_response(
                response,
                discovery_url=candidate.discovery_url,
                media_type=media_type,
            )
        except Exception as exc:
            logger.debug("historical SEP validation failed: %s", repr(exc))
            if not _is_transient_validation_error(exc):
                retained[media_type] = None
            error_type, message = bounded_release_error(exc)
            errors.append(f"{media_type.upper()} {error_type}: {message}")
    return replace(
        candidate,
        html_url=retained["html"],
        pdf_url=retained["pdf"],
        discovery_error=bounded_messages(errors),
    )


def _is_transient_validation_error(exc: BaseException) -> bool:
    if isinstance(exc, httpx.TransportError):
        return True
    return isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code >= 500


def _label(value: str) -> str:
    return " ".join(value.split())
