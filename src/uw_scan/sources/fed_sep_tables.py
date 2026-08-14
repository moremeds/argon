"""Table-level parsing for official Federal Reserve SEP releases.

The publisher's accessible HTML changes shape across the 2020+ archive in four
bounded ways, each represented here as an explicit supported family rather than
a relaxed selector:

* the summary table is headed either ``Table 1.`` or, for the 2020 advance
  releases, ``Advance release of table 1 ...``;
* March and June publish four projection horizons while September and December
  publish five, so the horizon count is derived from the header and verified
  against the publisher's own three-fold repeat rather than hard-coded;
* range bounds separate with either U+2013 or U+002D while negative bounds
  always use U+002D, so ranges are matched against an anchored numeric grammar
  instead of split on a dash;
* only one page in the archive states participant totals in prose, so the
  Figure 2 dot table is the primary count source and prose is a cross-check
  that is enforced only when it names this release's own meeting.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Final

from bs4 import BeautifulSoup, Tag

from uw_scan.normalize import NormalizationError

SUMMARY_HEADING_PREFIXES: Final = ("Table 1.", "Advance release of table 1")
DOT_HEADING_PREFIX: Final = "Figure 2."
SUPPORTED_HORIZON_COUNTS: Final = frozenset({4, 5})

_VARIABLE_NAMES: Final = {
    "Change in real GDP": "real_gdp_growth",
    "Unemployment rate": "unemployment_rate",
    "PCE inflation": "pce_inflation",
    "Core PCE inflation": "core_pce_inflation",
    "Federal funds rate": "federal_funds_rate",
}

_NUMBER: Final = r"-?(?:\d+(?:\.\d+)?|\.\d+)"
_SINGLE_RE: Final = re.compile(rf"^({_NUMBER})$")
_RANGE_RE: Final = re.compile(rf"^({_NUMBER})[–-]({_NUMBER})$")
_DOT_COUNT_RE: Final = re.compile(r"^\d+$")

_DECLARATION_RE: Final = re.compile(
    r"([A-Za-z]+|\d+) participants submitted information in conjunction with the "
    r"([A-Z][a-z]+) (\d{1,2})[–-](\d{1,2}), (\d{4}), meeting",
)
_ABSTENTION_RE: Final = re.compile(
    r"([A-Za-z]+|\d+) of these \d+ participants did not submit projections for "
    r"(\d{4}|the longer run)",
    flags=re.IGNORECASE,
)

_INTEGER_WORDS: Final = {
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

LONGER_RUN: Final = "Longer run"


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


def find_summary_table(soup: BeautifulSoup) -> Tag:
    for prefix in SUMMARY_HEADING_PREFIXES:
        table = _find_table(soup, heading_prefix=prefix)
        if table is not None:
            return table
    raise NormalizationError("SEP Table 1 table is missing")


def find_dot_table(soup: BeautifulSoup) -> Tag:
    table = _find_table(soup, heading_prefix=DOT_HEADING_PREFIX)
    if table is None:
        raise NormalizationError("SEP Figure 2 table is missing")
    return table


def _find_table(soup: BeautifulSoup, *, heading_prefix: str) -> Tag | None:
    for table in soup.find_all("table"):
        heading = table.find_previous(["h3", "h4", "h5", "h6"])
        if heading is not None and heading.get_text(" ", strip=True).startswith(
            heading_prefix
        ):
            return table
    return None


def _rows(table: Tag) -> list[list[str]]:
    return [
        [cell.get_text(" ", strip=True) for cell in row.find_all(["th", "td"])]
        for row in table.find_all("tr")
    ]


def _horizons_from_header(header: list[str], *, context: str) -> tuple[str, ...]:
    """Derive the horizon labels from the publisher's own three-fold repeat."""
    if not header or len(header) % 3:
        raise NormalizationError(f"SEP {context} headers changed")
    count = len(header) // 3
    if count not in SUPPORTED_HORIZON_COUNTS:
        raise NormalizationError(
            f"SEP {context} publishes an unsupported horizon count {count}"
        )
    horizons = tuple(header[:count])
    if header != list(horizons) * 3:
        raise NormalizationError(f"SEP {context} headers changed")
    return horizons


def parse_summary_table(table: Tag) -> tuple[SepProjection, ...]:
    rows = _rows(table)
    if len(rows) < 3:
        raise NormalizationError("SEP Table 1 headers changed")
    horizons = _horizons_from_header(rows[1], context="Table 1")
    width = len(rows[1])

    projections: list[SepProjection] = []
    seen_variables: set[str] = set()
    for row in rows[2:]:
        if len(row) != width + 1:
            continue
        label = next(
            (prefix for prefix in _VARIABLE_NAMES if row[0].startswith(prefix)), None
        )
        if label is None:
            continue
        variable = _VARIABLE_NAMES[label]
        if variable in seen_variables:
            raise NormalizationError(f"SEP Table 1 duplicate variable {variable}")
        seen_variables.add(variable)
        count = len(horizons)
        for index, horizon in enumerate(horizons):
            median_raw = row[1 + index]
            tendency_raw = row[1 + count + index]
            range_raw = row[1 + 2 * count + index]
            blank = [not cell for cell in (median_raw, tendency_raw, range_raw)]
            if all(blank):
                # The publisher omits the whole cell group when a variable has
                # no projection for a horizon (core PCE has no longer run).
                continue
            if any(blank):
                raise NormalizationError(
                    f"SEP Table 1 {variable} {horizon} is partially blank"
                )
            projections.append(
                SepProjection(
                    variable=variable,
                    horizon=horizon,
                    unit="percent",
                    median=_decimal(median_raw, context=f"{variable} {horizon} median"),
                    central_tendency=_range(
                        tendency_raw, context=f"{variable} {horizon} central tendency"
                    ),
                    range=_range(range_raw, context=f"{variable} {horizon} range"),
                )
            )
    missing = set(_VARIABLE_NAMES.values()) - seen_variables
    if missing:
        raise NormalizationError(f"SEP Table 1 missing variables: {sorted(missing)}")
    return tuple(projections)


def parse_dot_table(table: Tag) -> dict[str, tuple[SepDistributionPoint, ...]]:
    rows = _rows(table)
    if not rows or len(rows[0]) < 2:
        raise NormalizationError("SEP Figure 2 headers changed")
    horizons = tuple(rows[0][1:])
    if len(horizons) not in SUPPORTED_HORIZON_COUNTS:
        raise NormalizationError(
            f"SEP Figure 2 publishes an unsupported horizon count {len(horizons)}"
        )
    width = len(rows[0])
    distributions: dict[str, list[SepDistributionPoint]] = {
        horizon: [] for horizon in horizons
    }
    for row in rows[1:]:
        if len(row) != width:
            raise NormalizationError("SEP Figure 2 row width changed")
        value = _decimal(row[0], context="dot value")
        if value * 8 != (value * 8).to_integral_value():
            raise NormalizationError(f"SEP dot value {value} is not on a 1/8-point grid")
        for horizon, raw_count in zip(horizons, row[1:], strict=True):
            if not raw_count:
                continue
            if not _DOT_COUNT_RE.match(raw_count):
                raise NormalizationError(
                    f"SEP dot count is not a nonnegative integer: {raw_count!r}"
                )
            distributions[horizon].append(
                SepDistributionPoint(value=value, participant_count=int(raw_count))
            )
    totals = {
        horizon: sum(point.participant_count for point in points)
        for horizon, points in distributions.items()
    }
    empty = sorted(horizon for horizon, total in totals.items() if total <= 0)
    if empty:
        raise NormalizationError(f"SEP Figure 2 published no dots for: {empty}")
    return {
        horizon: tuple(sorted(points, key=lambda point: point.value))
        for horizon, points in distributions.items()
    }


def prose_participant_totals(
    soup: BeautifulSoup, *, meeting_date: date, horizons: tuple[str, ...]
) -> dict[str, int] | None:
    """Participant totals declared in prose for *this* release's meeting.

    Most archive pages state no total at all, and a page that does may also
    restate the previous SEP's total, so the declaration is matched on the
    meeting it names rather than on document order.  Returns ``None`` when this
    release publishes no declaration of its own.
    """
    text = " ".join(soup.get_text(" ").split())
    for match in _DECLARATION_RE.finditer(text):
        month, _first_day, last_day, year = match.group(2, 3, 4, 5)
        try:
            declared = datetime.strptime(
                f"{month} {last_day}, {year}", "%B %d, %Y"
            ).date()
        except ValueError as exc:
            raise NormalizationError("SEP participant declaration date is invalid") from exc
        if declared != meeting_date:
            continue
        total = _integer_word(match.group(1))
        totals = {horizon: total for horizon in horizons}
        sentence = text[match.end() : text.find(".", match.end()) + 1]
        for raw_count, raw_horizon in _ABSTENTION_RE.findall(sentence):
            horizon = (
                LONGER_RUN if raw_horizon.lower() == "the longer run" else raw_horizon
            )
            if horizon not in totals:
                raise NormalizationError(
                    f"SEP abstention names an unpublished horizon {horizon!r}"
                )
            totals[horizon] -= _integer_word(raw_count)
        return totals
    return None


def _integer_word(raw: str) -> int:
    try:
        return int(raw)
    except ValueError:
        try:
            return _INTEGER_WORDS[raw.lower()]
        except KeyError as exc:
            raise NormalizationError(f"unsupported participant count {raw!r}") from exc


def _range(raw: str, *, context: str) -> tuple[Decimal, Decimal]:
    """Parse a projection interval.

    Bounds are anchored on an explicit numeric grammar because the publisher
    uses both U+2013 and U+002D as separators while negative bounds always use
    U+002D -- splitting on a dash mis-reads ``-0.2–1.3`` and ``-2.5--2.2``.
    """
    text = raw.strip()
    if not text:
        raise NormalizationError(f"SEP {context} is missing")
    match = _RANGE_RE.match(text)
    if match is not None:
        return (
            _decimal(match.group(1), context=context),
            _decimal(match.group(2), context=context),
        )
    single = _SINGLE_RE.match(text)
    if single is None:
        raise NormalizationError(f"SEP {context} is not a published interval: {raw!r}")
    value = _decimal(single.group(1), context=context)
    return value, value


def _decimal(raw: str, *, context: str) -> Decimal:
    try:
        value = Decimal(raw.strip())
    except (InvalidOperation, ValueError) as exc:
        raise NormalizationError(f"SEP {context} is not numeric: {raw!r}") from exc
    if not value.is_finite():
        raise NormalizationError(f"SEP {context} must be finite")
    return value
