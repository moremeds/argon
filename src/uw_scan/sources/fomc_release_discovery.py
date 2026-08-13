"""Typed discovery of official Federal Reserve statement and SEP releases."""

from __future__ import annotations

import logging
import re
from collections.abc import Callable, Iterable
from dataclasses import replace
from datetime import date
from typing import Literal
from urllib.parse import urljoin, urlparse

import httpx
from bs4 import BeautifulSoup, Tag

from .fomc_release_contracts import (
    MAX_ERROR_LENGTH,
    EventClass,
    FomcDiscoveryPageOutcome,
    FomcDiscoveryResult,
    FomcReleaseCandidate,
    ReleaseDiscoveryError,
    ReleaseType,
    artifact_identity,
    bounded_messages,
    bounded_release_error,
    date_from_raw,
    deduplicate_release_candidates,
    require_official_response,
    url_origin,
)

logger = logging.getLogger(__name__)

_SEP_HISTORICAL_MARKER = re.compile(
    r"/FOMC(20\d{6})SEPcompilation\.pdf$", flags=re.IGNORECASE
)


def discover_current_release_candidates(
    raw: bytes,
    *,
    discovery_url: str,
    years: Iterable[int],
) -> list[FomcReleaseCandidate]:
    """Parse release links only inside typed current-calendar meeting fields."""

    wanted = set(years)
    soup = BeautifulSoup(raw, "html.parser")
    candidates: list[FomcReleaseCandidate] = []
    for row in soup.select(".fomc-meeting"):
        if not isinstance(row, Tag):
            continue
        year = _current_row_year(row)
        if year not in wanted:
            continue
        event_class = _event_class(row.get_text(" ", strip=True))
        for strong in row.find_all("strong"):
            label = _label(strong.get_text(" ", strip=True)).rstrip(":")
            if label == "Statement":
                candidate = _candidate_from_current_field(
                    strong.parent,
                    release_type="statement",
                    event_class=event_class,
                    discovery_url=discovery_url,
                )
            elif label == "Projection Materials":
                candidate = _candidate_from_current_field(
                    strong.parent,
                    release_type="sep",
                    event_class=None,
                    discovery_url=discovery_url,
                )
            else:
                continue
            if candidate is not None:
                candidates.append(candidate)
    return deduplicate_release_candidates(candidates)


def discover_official_release_candidates(
    *,
    get: Callable[[str], httpx.Response],
    base_url: str,
    calendar_path: str,
    years: Iterable[int],
    release_type: ReleaseType,
) -> list[FomcReleaseCandidate]:
    """Compatibility projection of the audited official discovery result."""

    return list(
        discover_official_release_result(
            get=get,
            base_url=base_url,
            calendar_path=calendar_path,
            years=years,
            release_type=release_type,
        ).candidates
    )


def discover_official_release_result(
    *,
    get: Callable[[str], httpx.Response],
    base_url: str,
    calendar_path: str,
    years: Iterable[int],
    release_type: ReleaseType,
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
            current = discover_current_release_candidates(
                calendar_response.content,
                discovery_url=calendar_url,
                years=requested_years,
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
            page_outcomes.append(
                FomcDiscoveryPageOutcome(
                    year=None,
                    url=calendar_url,
                    role="current_calendar",
                    status="ok",
                )
            )
            candidates.extend(
                item for item in current if item.release_type == release_type
            )

    for year in requested_years:
        if year >= date.today().year:
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
            historical = _historical_candidates(
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
        page_outcomes.append(
            FomcDiscoveryPageOutcome(
                year=year,
                url=history_url,
                role="historical_year",
                status="ok",
            )
        )
        for candidate in historical:
            if release_type == "statement":
                candidates.append(_complete_historical_statement(candidate, get=get))
            else:
                candidates.append(_validate_historical_sep(candidate, get=get))
    deduplicated = deduplicate_release_candidates(candidates)
    covered_years = {candidate.event_date.year for candidate in deduplicated}
    missing_years = tuple(year for year in requested_years if year not in covered_years)
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


def _candidate_from_current_field(
    field: Tag,
    *,
    release_type: ReleaseType,
    event_class: EventClass | None,
    discovery_url: str,
) -> FomcReleaseCandidate | None:
    urls: dict[str, str] = {}
    errors: list[str] = []
    for link in field.find_all("a", href=True):
        media_type = _label(link.get_text(" ", strip=True)).lower()
        if media_type not in ("html", "pdf"):
            continue
        href = str(link["href"])
        url = urljoin(discovery_url, href)
        if url_origin(url) != url_origin(discovery_url):
            errors.append(f"rejected off-host {media_type.upper()} link")
            continue
        try:
            artifact_identity(url, release_type=release_type, media_type=media_type)
        except ValueError as exc:
            logger.debug("rejecting incoherent current release URL: %s", repr(exc))
            errors.append(f"rejected incoherent {media_type.upper()} link")
            continue
        urls[media_type] = url
    if not urls:
        return None

    identities = {
        artifact_identity(url, release_type=release_type, media_type=media_type)
        for media_type, url in urls.items()
    }
    if len(identities) != 1:
        raise ReleaseDiscoveryError("current meeting links identify different releases")
    stem, event_date = identities.pop()
    for media_type in ("html", "pdf"):
        if media_type not in urls:
            errors.append(f"missing {media_type.upper()} counterpart")
    prefix = "fomc-statement" if release_type == "statement" else "fed-sep"
    return FomcReleaseCandidate(
        release_key=f"{prefix}:{stem}",
        release_type=release_type,
        event_date=event_date,
        event_class=event_class,
        discovery_url=discovery_url,
        html_url=urls.get("html"),
        pdf_url=urls.get("pdf"),
        discovery_error=bounded_messages(errors),
    )


def _historical_candidates(
    raw: bytes,
    *,
    discovery_url: str,
    year: int,
    release_type: ReleaseType,
) -> list[FomcReleaseCandidate]:
    soup = BeautifulSoup(raw, "html.parser")
    candidates: list[FomcReleaseCandidate] = []
    for panel in soup.select(".panel.panel-default.panel-padded"):
        if not isinstance(panel, Tag):
            continue
        heading = panel.find(re.compile(r"^h[1-6]$"))
        heading_text = heading.get_text(" ", strip=True) if heading else ""
        if str(year) not in heading_text:
            continue
        if release_type == "statement":
            event_class: EventClass | None = _event_class(heading_text)
            links = [
                link
                for link in panel.find_all("a", href=True)
                if _label(link.get_text(" ", strip=True)) == "Statement"
            ]
        else:
            event_class = None
            links = [
                link
                for link in panel.find_all("a", href=True)
                if _label(link.get_text(" ", strip=True)).startswith(
                    "SEP: Individual Projections"
                )
            ]
        for link in links:
            marker_url = urljoin(discovery_url, str(link["href"]))
            if url_origin(marker_url) != url_origin(discovery_url):
                continue
            try:
                if release_type == "statement":
                    stem, event_date = artifact_identity(
                        marker_url, release_type="statement", media_type="html"
                    )
                    html_url = marker_url
                    pdf_url = None
                    error = "missing PDF pending statement-page discovery"
                    prefix = "fomc-statement"
                else:
                    marker_match = _SEP_HISTORICAL_MARKER.search(
                        urlparse(marker_url).path
                    )
                    if marker_match is None:
                        continue
                    raw_date = marker_match.group(1)
                    stem = f"fomcprojtabl{raw_date}"
                    event_date = date_from_raw(raw_date)
                    html_url = urljoin(discovery_url, f"/monetarypolicy/{stem}.htm")
                    pdf_url = urljoin(
                        discovery_url, f"/monetarypolicy/files/{stem}.pdf"
                    )
                    error = "historical SEP canonical URLs require validation"
                    prefix = "fed-sep"
            except ValueError as exc:
                logger.debug(
                    "rejecting incoherent historical release URL: %s", repr(exc)
                )
                continue
            candidates.append(
                FomcReleaseCandidate(
                    release_key=f"{prefix}:{stem}",
                    release_type=release_type,
                    event_date=event_date,
                    event_class=event_class,
                    discovery_url=discovery_url,
                    html_url=html_url,
                    pdf_url=pdf_url,
                    discovery_error=error,
                )
            )
    return deduplicate_release_candidates(candidates)


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
        return replace(
            candidate,
            pdf_url=None,
            discovery_error=f"{error_type}: {message}"[:MAX_ERROR_LENGTH],
        )


def _validate_historical_sep(
    candidate: FomcReleaseCandidate,
    *,
    get: Callable[[str], httpx.Response],
) -> FomcReleaseCandidate:
    valid: dict[str, str] = {}
    errors: list[str] = []
    for media_type, url in (("html", candidate.html_url), ("pdf", candidate.pdf_url)):
        assert url is not None
        try:
            response = get(url)
            require_official_response(
                response,
                discovery_url=candidate.discovery_url,
                media_type=media_type,
            )
            valid[media_type] = url
        except Exception as exc:
            logger.debug("historical SEP validation failed: %s", repr(exc))
            error_type, message = bounded_release_error(exc)
            errors.append(f"{media_type.upper()} {error_type}: {message}")
    return replace(
        candidate,
        html_url=valid.get("html"),
        pdf_url=valid.get("pdf"),
        discovery_error=bounded_messages(errors),
    )


def _current_row_year(row: Tag) -> int | None:
    panel = row.find_parent(class_="panel")
    if not isinstance(panel, Tag):
        return None
    heading = panel.find(re.compile(r"^h[1-6]$"))
    if heading is None:
        return None
    match = re.search(r"\b(20\d{2}) FOMC Meetings\b", heading.get_text(" ", strip=True))
    return int(match.group(1)) if match else None


def _event_class(text: str) -> EventClass:
    normalized = _label(text).lower()
    if "notation vote" in normalized:
        return "notation_vote"
    if "unscheduled" in normalized:
        return "unscheduled_meeting"
    return "scheduled_meeting"


def _label(value: str) -> str:
    return " ".join(value.split())
