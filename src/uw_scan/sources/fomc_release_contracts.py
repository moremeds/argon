"""Typed identities and URL validation for official FOMC/SEP releases."""

from __future__ import annotations

import re
from collections.abc import Iterable
from dataclasses import dataclass, replace
from datetime import date
from typing import Literal
from urllib.parse import urlparse

import httpx

ReleaseType = Literal["statement", "sep"]
EventClass = Literal["scheduled_meeting", "unscheduled_meeting", "notation_vote"]
DiscoveryPageRole = Literal["current_calendar", "historical_year"]
DiscoveryPageStatus = Literal["ok", "not_found", "error"]

_STATEMENT_KEY = re.compile(r"^fomc-statement:(monetary(20\d{6})a)$")
_STATEMENT_HTML = re.compile(r"/(monetary(20\d{6})a)\.htm$")
_STATEMENT_PDF = re.compile(r"/(monetary(20\d{6})a)1\.pdf$")
_SEP_KEY = re.compile(r"^fed-sep:(fomcprojtabl(20\d{6}))$")
_SEP_HTML = re.compile(r"/(fomcprojtabl(20\d{6}))\.htm$")
_SEP_HTML_ALIAS = re.compile(r"/fomcprojtable(20\d{6})\.htm$")
_SEP_PDF = re.compile(r"/(fomcprojtabl(20\d{6}))\.pdf$")
MAX_ERROR_LENGTH = 500


class ReleaseDiscoveryError(ValueError):
    """Official release discovery produced an ambiguous candidate set."""


@dataclass(frozen=True)
class FomcDiscoveryPageOutcome:
    """Immutable audit outcome for one bounded official discovery page."""

    year: int | None
    url: str
    role: DiscoveryPageRole
    status: DiscoveryPageStatus
    error_type: str | None = None
    error_message: str | None = None

    def __post_init__(self) -> None:
        if self.role not in ("current_calendar", "historical_year"):
            raise ValueError(f"unsupported discovery page role {self.role!r}")
        if self.status not in ("ok", "not_found", "error"):
            raise ValueError(f"unsupported discovery page status {self.status!r}")
        if self.role == "current_calendar" and self.year is not None:
            raise ValueError("current calendar page outcome requires year=None")
        if self.role == "historical_year" and self.year is None:
            raise ValueError("historical page outcome requires a year")
        url_origin(self.url)
        if self.status == "ok" and (
            self.error_type is not None or self.error_message is not None
        ):
            raise ValueError("successful page outcome cannot contain an error")
        if self.status != "ok" and (
            self.error_type is None or self.error_message is None
        ):
            raise ValueError("failed page outcome requires a bounded error")
        if any(
            value is not None and len(value) > MAX_ERROR_LENGTH
            for value in (self.error_type, self.error_message)
        ):
            raise ValueError("page outcome error exceeds bounded length")


@dataclass(frozen=True)
class FomcReleaseCandidate:
    release_key: str
    release_type: ReleaseType
    event_date: date
    event_class: EventClass | None
    discovery_url: str
    html_url: str | None
    pdf_url: str | None
    discovery_error: str | None = None

    def __post_init__(self) -> None:
        if self.release_type not in ("statement", "sep"):
            raise ValueError(f"unsupported release_type {self.release_type!r}")
        if self.release_type == "statement" and self.event_class is None:
            raise ValueError("statement candidates require a non-null event_class")
        if self.release_type == "sep" and self.event_class is not None:
            raise ValueError("SEP candidates require event_class=None")
        if self.event_class not in (
            None,
            "scheduled_meeting",
            "unscheduled_meeting",
            "notation_vote",
        ):
            raise ValueError(f"unsupported event_class {self.event_class!r}")

        key_pattern = _STATEMENT_KEY if self.release_type == "statement" else _SEP_KEY
        key_match = key_pattern.fullmatch(self.release_key)
        if key_match is None:
            raise ValueError("release key does not match release type")
        if date_from_raw(key_match.group(2)) != self.event_date:
            raise ValueError("release key date does not match event_date")

        origin = url_origin(self.discovery_url)
        for label, value in (("HTML", self.html_url), ("PDF", self.pdf_url)):
            if value is None:
                continue
            if url_origin(value) != origin:
                raise ValueError(f"{label} URL is not on the configured Fed host")
            stem, artifact_date = artifact_identity(
                value, release_type=self.release_type, media_type=label.lower()
            )
            if stem != key_match.group(1) or artifact_date != self.event_date:
                raise ValueError(f"{label} URL does not match release key and date")
        if (
            self.discovery_error is not None
            and len(self.discovery_error) > MAX_ERROR_LENGTH
        ):
            raise ValueError("discovery_error exceeds bounded length")


@dataclass(frozen=True)
class FomcDiscoveryResult:
    """Deterministic candidate projection plus explicit page coverage audit."""

    candidates: tuple[FomcReleaseCandidate, ...]
    page_outcomes: tuple[FomcDiscoveryPageOutcome, ...]
    coverage_complete: bool
    missing_years: tuple[int, ...]

    def __post_init__(self) -> None:
        candidate_keys = tuple(item.release_key for item in self.candidates)
        if candidate_keys != tuple(sorted(set(candidate_keys))):
            raise ValueError("discovery result candidates must be unique and sorted")
        page_keys = tuple(_page_outcome_sort_key(item) for item in self.page_outcomes)
        if page_keys != tuple(sorted(set(page_keys))):
            raise ValueError("discovery page outcomes must be unique and sorted")
        if self.missing_years != tuple(sorted(set(self.missing_years))):
            raise ValueError("missing_years must be unique and sorted")
        if self.coverage_complete != (not self.missing_years):
            raise ValueError("coverage_complete must agree with missing_years")


def deduplicate_release_candidates(
    candidates: Iterable[FomcReleaseCandidate],
) -> list[FomcReleaseCandidate]:
    """Collapse compatible provenance duplicates and reject identity conflicts."""

    by_key: dict[str, FomcReleaseCandidate] = {}
    for candidate in candidates:
        existing = by_key.get(candidate.release_key)
        if existing is None:
            by_key[candidate.release_key] = candidate
            continue
        if (
            existing.release_type != candidate.release_type
            or existing.event_date != candidate.event_date
            or existing.event_class != candidate.event_class
        ):
            raise ReleaseDiscoveryError(
                f"conflicting duplicate release key {candidate.release_key}"
            )
        html_url = _merge_artifact_url(
            existing.html_url, candidate.html_url, release_key=candidate.release_key
        )
        pdf_url = _merge_artifact_url(
            existing.pdf_url, candidate.pdf_url, release_key=candidate.release_key
        )
        by_key[candidate.release_key] = replace(
            existing,
            discovery_url=min(existing.discovery_url, candidate.discovery_url),
            html_url=html_url,
            pdf_url=pdf_url,
            discovery_error=_merged_discovery_error(
                existing.discovery_error,
                candidate.discovery_error,
                html_url=html_url,
                pdf_url=pdf_url,
            ),
        )
    return [by_key[key] for key in sorted(by_key)]


def _merge_artifact_url(
    first: str | None,
    second: str | None,
    *,
    release_key: str,
) -> str | None:
    if first is not None and second is not None and first != second:
        raise ReleaseDiscoveryError(f"conflicting duplicate release key {release_key}")
    return first or second


def _merged_discovery_error(
    first: str | None,
    second: str | None,
    *,
    html_url: str | None,
    pdf_url: str | None,
) -> str | None:
    stale_errors: set[str] = set()
    if html_url is not None:
        stale_errors.add("missing HTML counterpart")
    if pdf_url is not None:
        stale_errors.update(
            {
                "missing PDF counterpart",
                "missing PDF pending statement-page discovery",
            }
        )
    if html_url is not None and pdf_url is not None:
        stale_errors.add("historical SEP canonical URLs require validation")
    messages = [
        message
        for error in (first, second)
        if error
        for message in error.split("; ")
        if message not in stale_errors
    ]
    return bounded_messages(messages)


def bounded_release_error(exc: BaseException) -> tuple[str, str]:
    error_type = type(exc).__name__
    message = " ".join(str(exc).split()) or error_type
    return error_type, message[:MAX_ERROR_LENGTH]


def _page_outcome_sort_key(
    outcome: FomcDiscoveryPageOutcome,
) -> tuple[int, int, str]:
    return (
        0 if outcome.role == "current_calendar" else 1,
        outcome.year if outcome.year is not None else -1,
        outcome.url,
    )


def require_official_response(
    response: httpx.Response,
    *,
    discovery_url: str,
    media_type: Literal["html", "pdf"],
) -> None:
    response.raise_for_status()
    if url_origin(str(response.url)) != url_origin(discovery_url):
        raise ReleaseDiscoveryError("response redirected off configured Fed host")
    content_type = response.headers.get("content-type", "").lower()
    if media_type == "html":
        if not response.content or (
            "html" not in content_type and b"<" not in response.content[:1000]
        ):
            raise ReleaseDiscoveryError("official HTML response content is invalid")
    elif not response.content or (
        "pdf" not in content_type and not response.content.startswith(b"%PDF")
    ):
        raise ReleaseDiscoveryError("official PDF response content is invalid")


def artifact_identity(
    url: str,
    *,
    release_type: ReleaseType,
    media_type: Literal["html", "pdf"],
) -> tuple[str, date]:
    path = urlparse(url).path
    if release_type == "statement":
        pattern = _STATEMENT_HTML if media_type == "html" else _STATEMENT_PDF
    else:
        pattern = _SEP_HTML if media_type == "html" else _SEP_PDF
    match = pattern.search(path)
    if match is None and release_type == "sep" and media_type == "html":
        alias_match = _SEP_HTML_ALIAS.search(path)
        if alias_match is not None:
            raw_date = alias_match.group(1)
            return f"fomcprojtabl{raw_date}", date_from_raw(raw_date)
    if match is None:
        raise ValueError("artifact URL does not match release type")
    return match.group(1), date_from_raw(match.group(2))


def url_origin(url: str) -> tuple[str, str]:
    parsed = urlparse(url)
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise ValueError("official URL must be absolute HTTP(S)")
    return parsed.scheme.lower(), parsed.netloc.lower()


def date_from_raw(raw: str) -> date:
    return date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))


def bounded_messages(messages: Iterable[str]) -> str | None:
    joined = "; ".join(dict.fromkeys(messages))
    return joined[:MAX_ERROR_LENGTH] or None
