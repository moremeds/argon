"""Independent whole-page anchor census for FOMC release discovery."""

from __future__ import annotations

import logging

import re
from collections.abc import Iterable
from datetime import date
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .fomc_release_contracts import (
    FomcDiscoverySlotOutcome,
    ReleaseType,
    artifact_identity,
    bounded_messages,
    date_from_raw,
    url_origin,
)

logger = logging.getLogger(__name__)

_SEP_HISTORICAL_MARKER = re.compile(
    r"/FOMC(20\d{6})SEPcompilation\.pdf$", flags=re.IGNORECASE
)
_STRATEGY_LABEL = "Statement on Longer-Run Goals and Monetary Policy Strategy"


def census_current_release_anchors(
    raw: bytes,
    *,
    discovery_url: str,
    years: Iterable[int],
    release_type: ReleaseType,
    as_of_date: date,
) -> tuple[FomcDiscoverySlotOutcome, ...]:
    """Census canonical artifacts without relying on meeting-row selectors."""

    wanted = set(years)
    soup = BeautifulSoup(raw, "html.parser")
    urls_by_identity: dict[str, list[str]] = {}
    errors_by_identity: dict[str, list[str]] = {}
    for link in soup.find_all("a", href=True):
        if not isinstance(link, Tag):
            continue
        if release_type == "statement" and _is_strategy_context(link):
            continue
        url = urljoin(discovery_url, str(link["href"]))
        identity = _canonical_identity(url, release_type=release_type)
        if identity is None:
            continue
        release_key, event_date = identity
        if event_date.year not in wanted or event_date > as_of_date:
            continue
        urls_by_identity.setdefault(release_key, []).append(url)
        if url_origin(url) != url_origin(discovery_url):
            errors_by_identity.setdefault(release_key, []).append(
                "canonical anchor points off configured Fed host"
            )

    slots: list[FomcDiscoverySlotOutcome] = []
    for release_key in sorted(urls_by_identity):
        year = _identity_year(release_key)
        errors = errors_by_identity.get(release_key, [])
        slots.append(
            _census_slot(
                slot_id=f"census:{release_key}",
                year=year,
                release_type=release_type,
                identity=release_key,
                errors=errors,
            )
        )
    return tuple(slots)


def census_historical_release_anchors(
    raw: bytes,
    *,
    discovery_url: str,
    year: int,
    release_type: ReleaseType,
) -> tuple[FomcDiscoverySlotOutcome, ...]:
    """Census exact historical markers without relying on panel classes."""

    soup = BeautifulSoup(raw, "html.parser")
    slots_by_identity: dict[str, FomcDiscoverySlotOutcome] = {}
    anonymous: list[FomcDiscoverySlotOutcome] = []
    for index, link in enumerate(soup.find_all("a", href=True)):
        if not isinstance(link, Tag):
            continue
        label = _label(link.get_text(" ", strip=True))
        if release_type == "statement":
            if label != "Statement":
                continue
        elif not label.startswith("SEP: Individual Projections"):
            continue

        url = urljoin(discovery_url, str(link["href"]))
        identity, errors = _historical_identity(
            url,
            discovery_url=discovery_url,
            year=year,
            release_type=release_type,
        )
        heading_text = _containing_heading_text(link)
        if str(year) not in heading_text:
            errors.append("historical marker lacks a usable meeting heading")
        elif not _has_event_class(heading_text):
            errors.append("historical marker heading lacks event classification")
        slot = _census_slot(
            slot_id=(
                f"census:{identity}"
                if identity is not None
                else f"census:{release_type}:{year}:anonymous:{index:03d}"
            ),
            year=year,
            release_type=release_type,
            identity=identity,
            errors=errors,
        )
        if identity is None:
            anonymous.append(slot)
            continue
        previous = slots_by_identity.get(identity)
        if previous is None or previous.status == "accepted":
            slots_by_identity[identity] = slot
    return tuple(
        sorted((*slots_by_identity.values(), *anonymous), key=lambda item: item.slot_id)
    )


def reconcile_anchor_census(
    extracted: tuple[FomcDiscoverySlotOutcome, ...],
    census: tuple[FomcDiscoverySlotOutcome, ...],
) -> tuple[FomcDiscoverySlotOutcome, ...]:
    """Reject census identities that the structured extractor failed to map."""

    reconciled = list(extracted)
    indices_by_identity: dict[str, list[int]] = {}
    for index, slot in enumerate(reconciled):
        if slot.identity is not None:
            indices_by_identity.setdefault(slot.identity, []).append(index)

    for census_slot in census:
        matching = indices_by_identity.get(census_slot.identity or "", [])
        if census_slot.status == "accepted" and matching:
            continue
        if census_slot.status == "rejected" and matching:
            for index in matching:
                if reconciled[index].status == "accepted":
                    reconciled[index] = _rejection_from_census(
                        reconciled[index], census_slot
                    )
            continue
        if census_slot.status == "accepted":
            reconciled.append(
                FomcDiscoverySlotOutcome(
                    slot_id=census_slot.slot_id,
                    year=census_slot.year,
                    release_type=census_slot.release_type,
                    identity=census_slot.identity,
                    status="rejected",
                    error_type="ReleaseDiscoveryError",
                    error_message=(
                        "canonical anchor identity was not mapped by structured extraction"
                    ),
                )
            )
        else:
            reconciled.append(census_slot)
    return tuple(sorted(reconciled, key=lambda item: item.slot_id))


def _canonical_identity(
    url: str, *, release_type: ReleaseType
) -> tuple[str, date] | None:
    for media_type in ("html", "pdf"):
        try:
            stem, event_date = artifact_identity(
                url, release_type=release_type, media_type=media_type
            )
        except ValueError as exc:
            logger.debug("census anchor is not a canonical release: %s", repr(exc))
            continue
        prefix = "fomc-statement" if release_type == "statement" else "fed-sep"
        return f"{prefix}:{stem}", event_date
    return None


def _historical_identity(
    url: str,
    *,
    discovery_url: str,
    year: int,
    release_type: ReleaseType,
) -> tuple[str | None, list[str]]:
    errors: list[str] = []
    identity: str | None = None
    if release_type == "statement":
        parsed = _canonical_identity(url, release_type="statement")
        if parsed is not None:
            identity, event_date = parsed
        else:
            event_date = None
            errors.append("historical Statement URL identity is incoherent")
    else:
        marker = _SEP_HISTORICAL_MARKER.search(urlparse(url).path)
        if marker is None:
            event_date = None
            errors.append("historical SEP marker identity is incoherent")
        else:
            raw_date = marker.group(1)
            event_date = date_from_raw(raw_date)
            identity = f"fed-sep:fomcprojtabl{raw_date}"
    if url_origin(url) != url_origin(discovery_url):
        errors.append("historical marker points off configured Fed host")
    if event_date is not None and event_date.year != year:
        errors.append("historical marker date does not match page year")
    return identity, errors


def _census_slot(
    *,
    slot_id: str,
    year: int,
    release_type: ReleaseType,
    identity: str | None,
    errors: list[str],
) -> FomcDiscoverySlotOutcome:
    message = bounded_messages(errors)
    if message is None:
        return FomcDiscoverySlotOutcome(
            slot_id=slot_id,
            year=year,
            release_type=release_type,
            identity=identity,
            status="accepted",
        )
    return FomcDiscoverySlotOutcome(
        slot_id=slot_id,
        year=year,
        release_type=release_type,
        identity=identity,
        status="rejected",
        error_type="ReleaseDiscoveryError",
        error_message=message,
    )


def _rejection_from_census(
    extracted: FomcDiscoverySlotOutcome,
    census: FomcDiscoverySlotOutcome,
) -> FomcDiscoverySlotOutcome:
    return FomcDiscoverySlotOutcome(
        slot_id=extracted.slot_id,
        year=extracted.year,
        release_type=extracted.release_type,
        identity=extracted.identity,
        status="rejected",
        error_type=census.error_type,
        error_message=census.error_message,
    )


def _identity_year(identity: str) -> int:
    match = re.search(r"(20\d{2})\d{4}[a]?$", identity)
    if match is None:  # pragma: no cover - constructed only from canonical identities
        raise ValueError("canonical identity lacks a year")
    return int(match.group(1))


def _label(value: str) -> str:
    return " ".join(value.split())


def _is_strategy_context(link: Tag) -> bool:
    if _label(link.get_text(" ", strip=True)) == _STRATEGY_LABEL:
        return True
    parent = link.parent
    if not isinstance(parent, Tag):
        return False
    return any(
        _label(sibling.get_text(" ", strip=True)) == _STRATEGY_LABEL
        for sibling in parent.find_all("a", recursive=False)
    )


def _has_event_class(heading: str) -> bool:
    normalized = heading.lower()
    return "meeting" in normalized or "notation vote" in normalized


def _containing_heading_text(link: Tag) -> str:
    for parent in link.parents:
        if not isinstance(parent, Tag) or parent.name in ("body", "html"):
            break
        heading = parent.find(re.compile(r"^h[1-6]$"))
        if isinstance(heading, Tag):
            return _label(heading.get_text(" ", strip=True))
    return ""
