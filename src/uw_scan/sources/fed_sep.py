"""Official Federal Reserve Summary of Economic Projections source.

The Fed's accessible HTML is the machine-readable representation, but its
request-specific Akamai footer makes exact HTML bytes unstable.  The matching
official PDF is therefore the primary immutable release artifact.  Both exact
representations are retained and the HTML parser is intentionally strict.

Artifact acquisition identity (``PARSER_VERSION``) and semantic parsing identity
(``SEMANTIC_PARSER_VERSION``) are deliberately separate: reprocessing an
unchanged artifact with an improved semantic parser must not rewrite the
immutable metadata already recorded for those exact bytes.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import date, datetime, time
from typing import Final
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.normalize import NormalizationError

from .fed_sep_tables import (
    SepDistributionPoint,
    SepProjection,
    find_dot_table,
    find_summary_table,
    parse_dot_table,
    parse_summary_table,
    prose_participant_totals,
)
from .fomc_release_contracts import artifact_identity

logger = logging.getLogger(__name__)

PARSER_VERSION: Final = "fed_sep.v1"
SEMANTIC_PARSER_VERSION: Final = "fed_sep.v2"
SOURCE: Final = "federal_reserve_sep"

_EASTERN: Final = ZoneInfo("America/New_York")
_RELEASE_TIME_RE: Final = re.compile(
    r"For release at (\d{1,2}):(\d{2})\s+([ap])\.m\.,?\s+(E[DS]T),?\s+"
    r"([A-Z][a-z]+ \d{1,2}, \d{4})",
    flags=re.IGNORECASE,
)

__all__ = [
    "PARSER_VERSION",
    "SEMANTIC_PARSER_VERSION",
    "SOURCE",
    "FedSepProvider",
    "SepDistributionPoint",
    "SepFetchOutcome",
    "SepProjection",
    "SepRelease",
    "SepReleaseTimestamp",
    "SepSourceBundle",
    "parse_sep_release",
    "release_timestamp",
]


@dataclass(frozen=True)
class SepReleaseTimestamp:
    """The publication instant plus the publisher's own timezone label.

    December pages in the official archive declare ``EDT`` even though December
    is ``EST``; the FOMC statement for the same release event declares ``EST``.
    The instant is therefore resolved as the published wall clock in Eastern
    time and the disagreement is retained as parser audit metadata.  Obeying the
    literal label would place availability an hour early, which would leak
    future information into point-in-time replay.
    """

    published_at: datetime
    declared_timezone: str
    calendar_timezone: str

    @property
    def label_matches_calendar(self) -> bool:
        return self.declared_timezone == self.calendar_timezone


@dataclass(frozen=True)
class SepRelease:
    release_date: date
    meeting_date: date
    published_at: datetime
    source_url: str
    accessible_source_url: str
    source_record_id: str
    projections: tuple[SepProjection, ...]
    parser_version: str = SEMANTIC_PARSER_VERSION
    declared_timezone: str = ""
    calendar_timezone: str = ""
    #: Whether this release stated its own participant total in prose.  Most
    #: archive pages do not, so the Figure 2 dot table is the primary count and
    #: the prose is an independent cross-check only when it is published.
    prose_total_declared: bool = False

    @property
    def timezone_label_matches_calendar(self) -> bool:
        return self.declared_timezone == self.calendar_timezone


@dataclass(frozen=True)
class SepSourceBundle:
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
    ) -> "SepSourceBundle":
        # Exact evidence must be preservable before the publication instant is
        # normalized; the required timestamp check lives in parse_sep_release.
        stamp = optional_release_timestamp(accessible_bytes, expected_date=meeting_date)
        published_at = stamp.published_at if stamp is not None else None
        inferred_stem, inferred_date = artifact_identity(
            accessible_url,
            release_type="sep",
            media_type="html",
        )
        if inferred_date != meeting_date:
            raise ValueError("SEP URL date does not match meeting_date")
        record_base = release_key or f"fed-sep:{inferred_stem}"
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


def parse_sep_release(bundle: SepSourceBundle) -> SepRelease:
    raw = bundle.accessible_artifact.raw_bytes
    if raw is None:
        raise NormalizationError("SEP accessible artifact is missing raw bytes")
    soup = BeautifulSoup(raw, "html.parser")

    projections = parse_summary_table(find_summary_table(soup))
    distributions = parse_dot_table(find_dot_table(soup))

    policy_horizons = tuple(
        item.horizon for item in projections if item.variable == "federal_funds_rate"
    )
    if tuple(distributions) != policy_horizons:
        raise NormalizationError(
            "SEP Figure 2 horizons do not match the published policy horizons: "
            f"{list(distributions)} != {list(policy_horizons)}"
        )

    declared_totals = prose_participant_totals(
        soup, meeting_date=bundle.meeting_date, horizons=policy_horizons
    )
    if declared_totals is not None:
        for horizon, points in distributions.items():
            actual_total = sum(point.participant_count for point in points)
            expected_total = declared_totals[horizon]
            if actual_total != expected_total:
                raise NormalizationError(
                    f"SEP {horizon} participant total {actual_total} != {expected_total}"
                )

    output = tuple(
        SepProjection(
            variable=projection.variable,
            horizon=projection.horizon,
            unit=projection.unit,
            central_tendency=projection.central_tendency,
            range=projection.range,
            median=projection.median,
            participant_distribution=(
                distributions.get(projection.horizon, ())
                if projection.variable == "federal_funds_rate"
                else ()
            ),
        )
        for projection in projections
    )
    if not output:
        raise NormalizationError("SEP Table 1 produced no projections")

    stamp = release_timestamp(raw, expected_date=bundle.meeting_date)
    return SepRelease(
        release_date=stamp.published_at.date(),
        meeting_date=bundle.meeting_date,
        published_at=stamp.published_at,
        source_url=bundle.primary_artifact.source_url or "",
        accessible_source_url=bundle.accessible_artifact.source_url or "",
        source_record_id=bundle.release_key,
        projections=output,
        parser_version=SEMANTIC_PARSER_VERSION,
        declared_timezone=stamp.declared_timezone,
        calendar_timezone=stamp.calendar_timezone,
        prose_total_declared=declared_totals is not None,
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
    return MacroSourceArtifact(
        source=SOURCE,
        source_kind="official",
        source_record_id=source_record_id,
        source_url=source_url,
        published_at=published_at,
        available_at=published_at or retrieved_at,
        retrieved_at=retrieved_at,
        last_seen_at=retrieved_at,
        content_hash=content_hash,
        parser_version=PARSER_VERSION,
        quality_status="partial",
        cost_class="free_official",
        media_type=media_type,
        content_length=content_length,
        raw_bytes=raw_bytes,
    )


def release_timestamp(raw: bytes, *, expected_date: date) -> SepReleaseTimestamp:
    """Resolve the publication instant, or fail closed."""
    text = " ".join(BeautifulSoup(raw, "html.parser").get_text(" ").split())
    match = _RELEASE_TIME_RE.search(text)
    if match is None:
        raise NormalizationError("SEP release timestamp is missing")
    try:
        release_date = datetime.strptime(match.group(5), "%B %d, %Y").date()
    except ValueError as exc:
        raise NormalizationError("SEP release date is invalid") from exc
    if release_date != expected_date:
        raise NormalizationError(
            f"SEP release date {release_date} != meeting date {expected_date}"
        )
    hour = int(match.group(1)) % 12
    if match.group(3).lower() == "p":
        hour += 12
    published_at = datetime.combine(
        release_date,
        time(hour=hour, minute=int(match.group(2))),
        tzinfo=_EASTERN,
    )
    calendar_timezone = published_at.tzname() or ""
    return SepReleaseTimestamp(
        published_at=published_at,
        declared_timezone=match.group(4).upper(),
        calendar_timezone=calendar_timezone,
    )


def optional_release_timestamp(
    raw: bytes, *, expected_date: date
) -> SepReleaseTimestamp | None:
    """Resolve the publication instant, or ``None`` when it is not yet known."""
    try:
        return release_timestamp(raw, expected_date=expected_date)
    except NormalizationError as exc:
        logger.debug("SEP publication instant unavailable: %s", repr(exc))
        return None


# Compatibility re-export: acquisition lives in a cohesive submodule so the
# semantic SEP parser remains below the project's module-size target.
from .fed_sep_provider import FedSepProvider, SepFetchOutcome  # noqa: E402,F401
