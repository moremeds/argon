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

_STATEMENT_KEY = re.compile(r"^fomc-statement:(monetary(20\d{6})a)$")
_STATEMENT_HTML = re.compile(r"/(monetary(20\d{6})a)\.htm$")
_STATEMENT_PDF = re.compile(r"/(monetary(20\d{6})a)1\.pdf$")
_SEP_KEY = re.compile(r"^fed-sep:(fomcprojtabl(20\d{6}))$")
_SEP_HTML = re.compile(r"/(fomcprojtabl(20\d{6}))\.htm$")
_SEP_PDF = re.compile(r"/(fomcprojtabl(20\d{6}))\.pdf$")
MAX_ERROR_LENGTH = 500


class ReleaseDiscoveryError(ValueError):
    """Official release discovery produced an ambiguous candidate set."""


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
        comparable_existing = replace(existing, discovery_url=candidate.discovery_url)
        if comparable_existing != candidate:
            raise ReleaseDiscoveryError(
                f"conflicting duplicate release key {candidate.release_key}"
            )
        by_key[candidate.release_key] = replace(
            existing,
            discovery_url=min(existing.discovery_url, candidate.discovery_url),
        )
    return [by_key[key] for key in sorted(by_key)]


def bounded_release_error(exc: BaseException) -> tuple[str, str]:
    error_type = type(exc).__name__
    message = " ".join(str(exc).split()) or error_type
    return error_type, message[:MAX_ERROR_LENGTH]


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
