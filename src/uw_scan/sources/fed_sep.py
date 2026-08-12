"""Official Federal Reserve Summary of Economic Projections source.

The Fed's accessible HTML is the machine-readable representation, but its
request-specific Akamai footer makes exact HTML bytes unstable.  The matching
official PDF is therefore the primary immutable release artifact.  Both exact
representations are retained and the HTML parser is intentionally strict.
"""

from __future__ import annotations

import logging
import re
from dataclasses import dataclass
from datetime import UTC, date, datetime, time
from decimal import Decimal, InvalidOperation
from typing import Final
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup, Tag

from uw_scan.macro_evidence import macro_artifact_content_identity
from uw_scan.models.macro import MacroSourceArtifact
from uw_scan.normalize import NormalizationError

from .fomc_calendar import _projection_pdf_urls_by_date, _projection_urls_by_date

logger = logging.getLogger(__name__)

PARSER_VERSION: Final = "fed_sep.v1"
SOURCE: Final = "federal_reserve_sep"


@dataclass(frozen=True)
class SepDistributionPoint:
    value: Decimal
    participant_count: int


@dataclass(frozen=True)
class SepProjection:
    variable: str
    horizon: str
    unit: str
    central_tendency: tuple[Decimal, Decimal]
    range: tuple[Decimal, Decimal]
    median: Decimal
    participant_distribution: tuple[SepDistributionPoint, ...] = ()


@dataclass(frozen=True)
class SepRelease:
    release_date: date
    meeting_date: date
    published_at: datetime
    source_url: str
    accessible_source_url: str
    source_record_id: str
    projections: tuple[SepProjection, ...]


@dataclass(frozen=True)
class SepSourceBundle:
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
    ) -> "SepSourceBundle":
        published_at = _published_at(accessible_bytes, expected_date=meeting_date)
        record_base = f"fed-sep:{meeting_date.isoformat()}"
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

    def __enter__(self) -> "FedSepProvider":
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
        calendar_response = self._get(self.CALENDAR_PATH)
        calendar_response.raise_for_status()
        soup = BeautifulSoup(calendar_response.content, "html.parser")
        html_urls = _projection_urls_by_date(soup, self._base_url)
        pdf_urls = _projection_pdf_urls_by_date(soup, self._base_url)
        wanted = set(years)
        meeting_dates = sorted(
            meeting_date
            for meeting_date in html_urls.keys() & pdf_urls.keys()
            if meeting_date.year in wanted
        )
        if not meeting_dates:
            raise NormalizationError(
                "FOMC calendar did not contain paired SEP HTML/PDF links"
            )

        observed_at = retrieved_at or datetime.now(UTC)
        bundles: list[SepSourceBundle] = []
        for meeting_date in meeting_dates:
            accessible_response = self._get(html_urls[meeting_date])
            accessible_response.raise_for_status()
            pdf_response = self._get(pdf_urls[meeting_date])
            pdf_response.raise_for_status()
            bundles.append(
                SepSourceBundle.from_bytes(
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


def parse_sep_release(bundle: SepSourceBundle) -> SepRelease:
    raw = bundle.accessible_artifact.raw_bytes
    if raw is None:
        raise NormalizationError("SEP accessible artifact is missing raw bytes")
    soup = BeautifulSoup(raw, "html.parser")
    summary_table = _find_table(soup, heading_prefix="Table 1.")
    dot_table = _find_table(soup, heading_prefix="Figure 2.")

    projections = _parse_summary_table(summary_table)
    distributions = _parse_dot_table(dot_table)
    expected_totals = _expected_participant_totals(soup, tuple(distributions))
    for horizon, points in distributions.items():
        actual_total = sum(point.participant_count for point in points)
        expected_total = expected_totals[horizon]
        if actual_total != expected_total:
            raise NormalizationError(
                f"SEP {horizon} participant total {actual_total} != {expected_total}"
            )

    output: list[SepProjection] = []
    for projection in projections:
        output.append(
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
        )

    if not output:
        raise NormalizationError("SEP Table 1 produced no projections")
    published_at = _published_at(raw, expected_date=bundle.meeting_date)
    return SepRelease(
        release_date=published_at.date(),
        meeting_date=bundle.meeting_date,
        published_at=published_at,
        source_url=bundle.primary_artifact.source_url or "",
        accessible_source_url=bundle.accessible_artifact.source_url or "",
        source_record_id=f"fed-sep:{bundle.meeting_date.isoformat()}",
        projections=tuple(output),
    )


def _artifact(
    *,
    source_record_id: str,
    source_url: str,
    media_type: str,
    raw_bytes: bytes,
    published_at: datetime,
    retrieved_at: datetime,
) -> MacroSourceArtifact:
    content_hash, content_length = macro_artifact_content_identity(raw_bytes=raw_bytes)
    return MacroSourceArtifact(
        source=SOURCE,
        source_kind="official",
        source_record_id=source_record_id,
        source_url=source_url,
        published_at=published_at,
        available_at=published_at,
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


def _published_at(raw: bytes, *, expected_date: date) -> datetime:
    text = " ".join(BeautifulSoup(raw, "html.parser").get_text(" ").split())
    match = re.search(
        r"For release at (\d{1,2}):(\d{2})\s+([ap])\.m\.,?\s+(E[DS]T),?\s+"
        r"([A-Z][a-z]+ \d{1,2}, \d{4})",
        text,
        flags=re.IGNORECASE,
    )
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
        tzinfo=ZoneInfo("America/New_York"),
    )
    if published_at.tzname() != match.group(4).upper():
        raise NormalizationError("SEP release timezone does not match New York time")
    return published_at


def _find_table(soup: BeautifulSoup, *, heading_prefix: str) -> Tag:
    for table in soup.find_all("table"):
        heading = table.find_previous(["h3", "h4", "h5", "h6"])
        if heading is not None and heading.get_text(" ", strip=True).startswith(
            heading_prefix
        ):
            return table
    raise NormalizationError(f"SEP {heading_prefix.rstrip('.')} table is missing")


def _parse_summary_table(table: Tag) -> tuple[SepProjection, ...]:
    rows = [
        [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for row in table.find_all("tr")
    ]
    if len(rows) < 3 or len(rows[1]) != 12:
        raise NormalizationError("SEP Table 1 headers changed")
    horizons = tuple(rows[1][:4])
    variable_names = {
        "Change in real GDP": "real_gdp_growth",
        "Unemployment rate": "unemployment_rate",
        "PCE inflation": "pce_inflation",
        "Core PCE inflation": "core_pce_inflation",
        "Federal funds rate": "federal_funds_rate",
    }
    projections: list[SepProjection] = []
    seen_variables: set[str] = set()
    for row in rows[2:]:
        if len(row) != 13:
            continue
        label = next(
            (prefix for prefix in variable_names if row[0].startswith(prefix)), None
        )
        if label is None:
            continue
        variable = variable_names[label]
        if variable in seen_variables:
            raise NormalizationError(f"SEP Table 1 duplicate variable {variable}")
        seen_variables.add(variable)
        for index, horizon in enumerate(horizons):
            median_raw = row[1 + index]
            if not median_raw:
                continue
            projections.append(
                SepProjection(
                    variable=variable,
                    horizon=horizon,
                    unit="percent",
                    median=_decimal(median_raw, context=f"{variable} {horizon} median"),
                    central_tendency=_range(
                        row[5 + index], context=f"{variable} {horizon} central tendency"
                    ),
                    range=_range(row[9 + index], context=f"{variable} {horizon} range"),
                )
            )
    missing = set(variable_names.values()) - seen_variables
    if missing:
        raise NormalizationError(f"SEP Table 1 missing variables: {sorted(missing)}")
    return tuple(projections)


def _parse_dot_table(
    table: Tag,
) -> dict[str, tuple[SepDistributionPoint, ...]]:
    rows = [
        [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for row in table.find_all("tr")
    ]
    if not rows or len(rows[0]) != 5:
        raise NormalizationError("SEP Figure 2 headers changed")
    horizons = tuple(rows[0][1:])
    distributions: dict[str, list[SepDistributionPoint]] = {
        horizon: [] for horizon in horizons
    }
    for row in rows[1:]:
        if len(row) != 5:
            raise NormalizationError("SEP Figure 2 row width changed")
        value = _decimal(row[0], context="dot value")
        if value * 8 != (value * 8).to_integral_value():
            raise NormalizationError(
                f"SEP dot value {value} is not on a 1/8-point grid"
            )
        for horizon, raw_count in zip(horizons, row[1:], strict=True):
            if not raw_count:
                continue
            try:
                count = int(raw_count)
            except ValueError as exc:
                raise NormalizationError("SEP dot count is not an integer") from exc
            if count < 0:
                raise NormalizationError("SEP dot count must be nonnegative")
            distributions[horizon].append(
                SepDistributionPoint(value=value, participant_count=count)
            )
    return {
        horizon: tuple(sorted(points, key=lambda point: point.value))
        for horizon, points in distributions.items()
    }


def _expected_participant_totals(
    soup: BeautifulSoup, horizons: tuple[str, ...]
) -> dict[str, int]:
    text = " ".join(soup.get_text(" ").split())
    matches = re.findall(
        r"([A-Za-z]+|\d+) participants submitted information in conjunction with the "
        r"[A-Z][a-z]+ \d{1,2}[–-]\d{1,2}, \d{4}, meeting",
        text,
    )
    if not matches:
        raise NormalizationError("SEP participant count declaration is missing")
    total = _integer_word(matches[-1])
    expected = {horizon: total for horizon in horizons}
    for missing_horizon in re.findall(
        r"did not submit projections for (\d{4}|the longer run)",
        text,
        flags=re.IGNORECASE,
    ):
        normalized = (
            "Longer run"
            if missing_horizon.lower() == "the longer run"
            else missing_horizon
        )
        if normalized in expected:
            expected[normalized] -= 1
    return expected


def _integer_word(raw: str) -> int:
    words = {
        "zero": 0,
        "one": 1,
        "two": 2,
        "three": 3,
        "four": 4,
        "five": 5,
        "six": 6,
        "seven": 7,
        "eight": 8,
        "nine": 9,
        "ten": 10,
        "eleven": 11,
        "twelve": 12,
        "thirteen": 13,
        "fourteen": 14,
        "fifteen": 15,
        "sixteen": 16,
        "seventeen": 17,
        "eighteen": 18,
        "nineteen": 19,
        "twenty": 20,
    }
    try:
        return int(raw)
    except ValueError:
        try:
            return words[raw.lower()]
        except KeyError as exc:
            raise NormalizationError(f"unsupported participant count {raw!r}") from exc


def _range(raw: str, *, context: str) -> tuple[Decimal, Decimal]:
    normalized = raw.replace("–", "-").strip()
    if not normalized:
        raise NormalizationError(f"SEP {context} is missing")
    parts = normalized.split("-", 1)
    if len(parts) == 1:
        value = _decimal(parts[0], context=context)
        return value, value
    return _decimal(parts[0], context=context), _decimal(parts[1], context=context)


def _decimal(raw: str, *, context: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"SEP {context} is not numeric: {raw!r}") from exc
    if not value.is_finite():
        raise NormalizationError(f"SEP {context} must be finite")
    return value
