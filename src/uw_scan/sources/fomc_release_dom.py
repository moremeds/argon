"""DOM inventory parsing for official Federal Reserve release indexes."""

from __future__ import annotations

import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup, Tag

from .fomc_release_contracts import (
    EventClass,
    FomcDiscoverySlotOutcome,
    FomcReleaseCandidate,
    ReleaseDiscoveryError,
    ReleaseType,
    artifact_identity,
    bounded_messages,
    date_from_raw,
    deduplicate_release_candidates,
    url_origin,
)

logger = logging.getLogger(__name__)

_SEP_HISTORICAL_MARKER = re.compile(
    r"/FOMC(20\d{6})SEPcompilation\.pdf$", flags=re.IGNORECASE
)
_STRATEGY_LABEL = "Statement on Longer-Run Goals and Monetary Policy Strategy"


@dataclass(frozen=True)
class FomcPageInventory:
    candidates: tuple[FomcReleaseCandidate, ...]
    slots: tuple[FomcDiscoverySlotOutcome, ...]


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


def inventory_current_release_page(
    raw: bytes,
    *,
    discovery_url: str,
    years: Iterable[int],
    release_type: ReleaseType,
    as_of_date: date,
) -> FomcPageInventory:
    """Account for every relevant elapsed meeting row on the current page."""

    wanted = set(years)
    soup = BeautifulSoup(raw, "html.parser")
    candidates: list[FomcReleaseCandidate] = []
    slots: list[FomcDiscoverySlotOutcome] = []
    for row in soup.select(".fomc-meeting"):
        if not isinstance(row, Tag):
            continue
        year = _current_row_year(row)
        if year not in wanted:
            continue
        event_date = _current_row_event_date(row, year=year)
        if event_date is None:
            slots.append(
                _rejected_slot(
                    slot_id=f"{release_type}:{year}:unparseable-row",
                    year=year,
                    release_type=release_type,
                    identity=None,
                    message="meeting date is unparseable",
                )
            )
            continue
        if event_date > as_of_date:
            continue
        if _is_cancelled_row(row):
            continue
        field_label = (
            "Statement" if release_type == "statement" else "Projection Materials"
        )
        if release_type == "sep" and not _is_sep_row(row):
            continue
        field = next(
            (
                strong.parent
                for strong in row.find_all("strong")
                if _label(strong.get_text(" ", strip=True)).rstrip(":") == field_label
            ),
            None,
        )
        if release_type == "statement" and field is None and _is_strategy_only_row(row):
            continue
        prefix = (
            "fomc-statement:monetary"
            if release_type == "statement"
            else "fed-sep:fomcprojtabl"
        )
        suffix = "a" if release_type == "statement" else ""
        expected_identity = f"{prefix}{event_date:%Y%m%d}{suffix}"
        slot_id = f"{release_type}:{event_date.isoformat()}"
        if not isinstance(field, Tag):
            slots.append(
                _rejected_slot(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=expected_identity,
                    message=f"missing {field_label} field",
                )
            )
            continue
        try:
            candidate = _candidate_from_current_field(
                field,
                release_type=release_type,
                event_class=(
                    _event_class(row.get_text(" ", strip=True))
                    if release_type == "statement"
                    else None
                ),
                discovery_url=discovery_url,
            )
        except Exception as exc:
            logger.debug("FOMC release slot rejected: %s", repr(exc))
            slots.append(
                _rejected_slot(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=expected_identity,
                    message=str(exc),
                )
            )
            continue
        if candidate is None:
            slots.append(
                _rejected_slot(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=expected_identity,
                    message=f"{field_label} field exposed no coherent official artifact",
                )
            )
            continue
        if candidate.event_date != event_date:
            slots.append(
                _rejected_slot(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=expected_identity,
                    message="artifact identity does not match meeting row date",
                )
            )
            continue
        candidates.append(candidate)
        if candidate.discovery_error:
            slots.append(
                _rejected_slot(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=candidate.release_key,
                    message=candidate.discovery_error,
                )
            )
        else:
            slots.append(
                FomcDiscoverySlotOutcome(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=candidate.release_key,
                    status="accepted",
                )
            )
    return _inventory(candidates, slots)


def discover_historical_release_candidates(
    raw: bytes,
    *,
    discovery_url: str,
    year: int,
    release_type: ReleaseType,
) -> list[FomcReleaseCandidate]:
    """Parse exact typed release markers from one historical index page."""

    return list(
        inventory_historical_release_page(
            raw,
            discovery_url=discovery_url,
            year=year,
            release_type=release_type,
        ).candidates
    )


def inventory_historical_release_page(
    raw: bytes,
    *,
    discovery_url: str,
    year: int,
    release_type: ReleaseType,
) -> FomcPageInventory:
    """Account for every exact historical Statement/SEP marker."""

    soup = BeautifulSoup(raw, "html.parser")
    candidates: list[FomcReleaseCandidate] = []
    slots: list[FomcDiscoverySlotOutcome] = []
    for index, link in enumerate(_historical_links(soup, year, release_type)):
        slot_id = f"{release_type}:{year}:history:{index:03d}"
        marker_url = urljoin(discovery_url, str(link["href"]))
        identity: str | None = None
        try:
            if url_origin(marker_url) != url_origin(discovery_url):
                raise ValueError("historical marker points off configured Fed host")
            if release_type == "statement":
                stem, event_date = artifact_identity(
                    marker_url, release_type="statement", media_type="html"
                )
                identity = f"fomc-statement:{stem}"
                candidate = FomcReleaseCandidate(
                    release_key=identity,
                    release_type="statement",
                    event_date=event_date,
                    event_class=_event_class(_historical_heading_text(link)),
                    discovery_url=discovery_url,
                    html_url=marker_url,
                    pdf_url=None,
                    discovery_error="missing PDF pending statement-page discovery",
                )
            else:
                marker_match = _SEP_HISTORICAL_MARKER.search(urlparse(marker_url).path)
                if marker_match is None:
                    raise ValueError("historical SEP marker identity is incoherent")
                raw_date = marker_match.group(1)
                stem = f"fomcprojtabl{raw_date}"
                identity = f"fed-sep:{stem}"
                candidate = FomcReleaseCandidate(
                    release_key=identity,
                    release_type="sep",
                    event_date=date_from_raw(raw_date),
                    event_class=None,
                    discovery_url=discovery_url,
                    html_url=urljoin(discovery_url, f"/monetarypolicy/{stem}.htm"),
                    pdf_url=urljoin(discovery_url, f"/monetarypolicy/files/{stem}.pdf"),
                    discovery_error="historical SEP canonical URLs require validation",
                )
        except Exception as exc:
            logger.debug("FOMC release slot rejected: %s", repr(exc))
            slots.append(
                _rejected_slot(
                    slot_id=slot_id,
                    year=year,
                    release_type=release_type,
                    identity=identity,
                    message=str(exc),
                )
            )
            continue
        candidates.append(candidate)
        slots.append(
            FomcDiscoverySlotOutcome(
                slot_id=slot_id,
                year=year,
                release_type=release_type,
                identity=candidate.release_key,
                status="accepted",
            )
        )
    return _inventory(candidates, slots)


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


def _current_row_year(row: Tag) -> int | None:
    panel = row.find_parent(class_="panel")
    if not isinstance(panel, Tag):
        return None
    heading = panel.find(re.compile(r"^h[1-6]$"))
    if heading is None:
        return None
    match = re.search(r"\b(20\d{2}) FOMC Meetings\b", heading.get_text(" ", strip=True))
    return int(match.group(1)) if match else None


def _current_row_event_date(row: Tag, *, year: int) -> date | None:
    month_node = row.select_one(".fomc-meeting__month")
    date_node = row.select_one(".fomc-meeting__date")
    if month_node is None or date_node is None:
        return None
    month_label = _label(month_node.get_text(" ", strip=True)).split("/")[-1]
    try:
        month = datetime.strptime(month_label, "%B").month
    except ValueError as exc:
        logger.debug("FOMC month label is not a full month name: %s", repr(exc))
        try:
            month = datetime.strptime(month_label, "%b").month
        except ValueError as abbreviated_exc:
            logger.debug(
                "FOMC month label is not a month name: %s", repr(abbreviated_exc)
            )
            return None
    days = re.findall(r"\d{1,2}", date_node.get_text(" ", strip=True))
    if not days:
        return None
    try:
        return date(year, month, int(days[-1]))
    except ValueError as exc:
        logger.debug("FOMC meeting date is not a real calendar date: %s", repr(exc))
        return None


def _is_sep_row(row: Tag) -> bool:
    node = row.select_one(".fomc-meeting__date")
    return node is not None and "*" in node.get_text(" ", strip=True)


def _is_strategy_only_row(row: Tag) -> bool:
    labels = {_label(link.get_text(" ", strip=True)) for link in row.find_all("a")}
    return _STRATEGY_LABEL in labels


def _is_cancelled_row(row: Tag) -> bool:
    node = row.select_one(".fomc-meeting__date")
    return node is not None and "cancelled" in node.get_text(" ", strip=True).lower()


def _historical_links(
    soup: BeautifulSoup, year: int, release_type: ReleaseType
) -> list[Tag]:
    links: list[Tag] = []
    for panel in soup.select(".panel.panel-default.panel-padded"):
        if not isinstance(panel, Tag):
            continue
        heading = panel.find(re.compile(r"^h[1-6]$"))
        heading_text = heading.get_text(" ", strip=True) if heading else ""
        if str(year) not in heading_text:
            continue
        for link in panel.find_all("a", href=True):
            label = _label(link.get_text(" ", strip=True))
            if release_type == "statement" and label == "Statement":
                links.append(link)
            elif release_type == "sep" and label.startswith(
                "SEP: Individual Projections"
            ):
                links.append(link)
    return links


def _historical_heading_text(link: Tag) -> str:
    panel = link.find_parent(class_="panel")
    if not isinstance(panel, Tag):
        return ""
    heading = panel.find(re.compile(r"^h[1-6]$"))
    return heading.get_text(" ", strip=True) if heading else ""


def _rejected_slot(
    *,
    slot_id: str,
    year: int,
    release_type: ReleaseType,
    identity: str | None,
    message: str,
) -> FomcDiscoverySlotOutcome:
    return FomcDiscoverySlotOutcome(
        slot_id=slot_id,
        year=year,
        release_type=release_type,
        identity=identity,
        status="rejected",
        error_type="ReleaseDiscoveryError",
        error_message=(" ".join(message.split()) or "release slot rejected")[:500],
    )


def _inventory(
    candidates: list[FomcReleaseCandidate], slots: list[FomcDiscoverySlotOutcome]
) -> FomcPageInventory:
    deduplicated = tuple(deduplicate_release_candidates(candidates))
    return FomcPageInventory(
        candidates=deduplicated,
        slots=tuple(sorted(slots, key=lambda item: item.slot_id)),
    )


def _event_class(text: str) -> EventClass:
    normalized = _label(text).lower()
    if "notation vote" in normalized:
        return "notation_vote"
    if "unscheduled" in normalized:
        return "unscheduled_meeting"
    return "scheduled_meeting"


def _label(value: str) -> str:
    return " ".join(value.split())
