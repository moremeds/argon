"""Federal Reserve FOMC calendar and statement source."""

from __future__ import annotations

import calendar
import logging
import re
import unicodedata
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from uw_scan.normalize import NormalizationError

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class FomcMeeting:
    start_date: date
    end_date: date
    label: str
    action: str | None
    vote_split: str | None
    source_url: str | None
    statement_pdf_url: str | None
    projection_url: str | None
    projection_pdf_url: str | None
    source_record_id: str | None
    published_at: datetime | None
    target_range_lower: Decimal | None
    target_range_upper: Decimal | None

    def to_payload(self) -> dict[str, object]:
        return {
            "event_date": self.start_date,
            "event_end_date": self.end_date,
            "label": self.label,
            "action": self.action,
            "vote_split": self.vote_split,
            "source_url": self.source_url,
        }


class FomcCalendarProvider:
    BASE_URL = "https://www.federalreserve.gov"
    CALENDAR_PATH = "/monetarypolicy/fomccalendars.htm"

    def __init__(self, *, base_url: str = BASE_URL, timeout_s: float = 30.0):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(
            timeout=timeout_s,
            follow_redirects=True,
            trust_env=False,
        )

    def __enter__(self) -> "FomcCalendarProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_meetings(self, *, years: Iterable[int]) -> list[FomcMeeting]:
        response = self._get(self.CALENDAR_PATH)
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        statement_urls = _statement_urls_by_date(soup, self._base_url)
        statement_pdf_urls = _statement_pdf_urls_by_date(soup, self._base_url)
        projection_urls = _projection_urls_by_date(soup, self._base_url)
        projection_pdf_urls = _projection_pdf_urls_by_date(soup, self._base_url)
        meetings = _parse_meeting_lines(
            soup,
            years=years,
            statement_urls=statement_urls,
            statement_pdf_urls=statement_pdf_urls,
            projection_urls=projection_urls,
            projection_pdf_urls=projection_pdf_urls,
        )
        enriched: list[FomcMeeting] = []
        for meeting in meetings:
            action = meeting.action
            vote_split = meeting.vote_split
            target_range_lower = meeting.target_range_lower
            target_range_upper = meeting.target_range_upper
            published_at = meeting.published_at
            if meeting.source_url:
                try:
                    statement = self._get(
                        meeting.source_url.replace(self._base_url, "")
                    )
                    statement.raise_for_status()
                    action = action or _infer_action(statement.text)
                    vote_split = vote_split or _infer_vote_split(statement.text)
                    target_range = _infer_target_range(statement.text)
                    if target_range is not None:
                        target_range_lower, target_range_upper = target_range
                    published_at = published_at or _infer_published_at(
                        statement.text, meeting.end_date
                    )
                except httpx.HTTPError as exc:
                    logger.debug(
                        "skipping FOMC statement enrichment failure: %s", repr(exc)
                    )
            enriched.append(
                FomcMeeting(
                    start_date=meeting.start_date,
                    end_date=meeting.end_date,
                    label=meeting.label,
                    action=action,
                    vote_split=vote_split,
                    source_url=meeting.source_url,
                    statement_pdf_url=meeting.statement_pdf_url,
                    projection_url=meeting.projection_url,
                    projection_pdf_url=meeting.projection_pdf_url,
                    source_record_id=meeting.source_record_id,
                    published_at=published_at,
                    target_range_lower=target_range_lower,
                    target_range_upper=target_range_upper,
                )
            )
        return enriched

    def _get(self, path: str) -> httpx.Response:
        if path.startswith("http"):
            url = path
        else:
            url = f"{self._base_url}{path}"
        return self._client.get(url)


def _statement_urls_by_date(soup: BeautifulSoup, base_url: str) -> dict[date, str]:
    return _dated_document_urls(
        soup,
        base_url,
        patterns=(
            r"fomcstatement(20\d{6})\.htm$",
            r"/newsevents/pressreleases/monetary(20\d{6})a\.htm$",
        ),
    )


def _statement_pdf_urls_by_date(soup: BeautifulSoup, base_url: str) -> dict[date, str]:
    return _dated_document_urls(
        soup,
        base_url,
        patterns=(
            r"fomcstatement(20\d{6})\.pdf$",
            r"/monetarypolicy/files/monetary(20\d{6})a1\.pdf$",
        ),
    )


def _projection_urls_by_date(soup: BeautifulSoup, base_url: str) -> dict[date, str]:
    return _dated_document_urls(
        soup,
        base_url,
        patterns=(r"/monetarypolicy/fomcprojtabl(20\d{6})\.htm$",),
    )


def _projection_pdf_urls_by_date(soup: BeautifulSoup, base_url: str) -> dict[date, str]:
    return _dated_document_urls(
        soup,
        base_url,
        patterns=(r"/monetarypolicy/files/fomcprojtabl(20\d{6})\.pdf$",),
    )


def _dated_document_urls(
    soup: BeautifulSoup,
    base_url: str,
    *,
    patterns: tuple[str, ...],
) -> dict[date, str]:
    out: dict[date, str] = {}
    for link in soup.find_all("a", href=True):
        href = str(link["href"])
        match = next(
            (
                candidate
                for pattern in patterns
                if (candidate := re.search(pattern, href))
            ),
            None,
        )
        if match is None:
            continue
        raw = match.group(1)
        event_date = date(int(raw[:4]), int(raw[4:6]), int(raw[6:8]))
        out[event_date] = href if href.startswith("http") else f"{base_url}{href}"
    return out


def _parse_meeting_lines(
    soup: BeautifulSoup,
    *,
    years: Iterable[int],
    statement_urls: dict[date, str],
    statement_pdf_urls: dict[date, str],
    projection_urls: dict[date, str],
    projection_pdf_urls: dict[date, str],
) -> list[FomcMeeting]:
    wanted = set(years)
    month_lookup = {name: idx for idx, name in enumerate(calendar.month_name) if name}
    lines = [line.strip() for line in soup.get_text("\n").splitlines() if line.strip()]
    out: list[FomcMeeting] = []
    current_year: int | None = None
    current_month: int | None = None
    for line in lines:
        year_match = re.fullmatch(r"(20\d{2}) FOMC Meetings", line)
        if year_match:
            current_year = int(year_match.group(1))
            current_month = None
            continue
        if current_year not in wanted:
            continue
        if line in month_lookup:
            current_month = month_lookup[line]
            continue
        if current_month is None:
            continue
        day_match = re.fullmatch(r"(\d{1,2})(?:-(\d{1,2}))?\*?", line)
        if day_match is None:
            continue
        start_day = int(day_match.group(1))
        end_day = int(day_match.group(2) or start_day)
        start = date(current_year, current_month, start_day)
        end = date(current_year, current_month, end_day)
        label = f"{calendar.month_name[current_month]} {start_day}"
        if end_day != start_day:
            label = f"{calendar.month_name[current_month]} {start_day}-{end_day}"
        out.append(
            FomcMeeting(
                start_date=start,
                end_date=end,
                label=f"{label} FOMC",
                action=None,
                vote_split=None,
                source_url=statement_urls.get(end),
                statement_pdf_url=statement_pdf_urls.get(end),
                projection_url=projection_urls.get(end),
                projection_pdf_url=projection_pdf_urls.get(end),
                source_record_id=(
                    f"fomc-statement:{end.isoformat()}"
                    if statement_urls.get(end) is not None
                    else None
                ),
                published_at=None,
                target_range_lower=None,
                target_range_upper=None,
            )
        )
    return out


_HYPHENS = str.maketrans(
    {"‐": "-", "‑": "-", "‒": "-", "–": "-", "—": "-", "−": "-"}
)
_FRACTIONS = str.maketrans(
    {
        "¼": "1/4",
        "½": "1/2",
        "¾": "3/4",
        "⅛": "1/8",
        "⅜": "3/8",
        "⅝": "5/8",
        "⅞": "7/8",
        "⁄": "/",
    }
)
_NUMERIC_TOKEN = r"(?:\d+-\d+/\d+|\d+/\d+|\d+(?:\.\d+)?)"
_TARGET_RANGE = (
    rf"(?P<lower>{_NUMERIC_TOKEN})\s+to\s+"
    rf"(?P<upper>{_NUMERIC_TOKEN})\s+percent"
)
_DECISION_PATTERNS = (
    re.compile(
        rf"\bthe committee decided to "
        rf"(?P<verb>maintain|keep|raise|increase|lower) "
        rf"the target range for the federal funds rate "
        rf"(?:(?:at|to)\s+|by\s+{_NUMERIC_TOKEN}\s+percentage points?,?\s+to\s+)"
        rf"{_TARGET_RANGE}",
    ),
    re.compile(
        rf"\bthe federal open market committee directs the desk to undertake "
        rf"open market operations as necessary to (?P<verb>maintain|keep) "
        rf"the federal funds rate in a target range of {_TARGET_RANGE}",
    ),
)
_VOTER_NAME = re.compile(
    r"[A-Z][A-Za-z'’-]*"
    r"(?:\s+(?:[A-Z]\.|[A-Z][A-Za-z'’-]*)){1,4}"
    r"(?:,\s*(?:Chair|Vice Chair))?"
)


def _normalize_policy_text(value: str) -> str:
    normalized = unicodedata.normalize("NFKC", value)
    normalized = normalized.replace("\u00a0", " ")
    normalized = normalized.translate(_HYPHENS).translate(_FRACTIONS)
    return " ".join(normalized.split())


def _normalized_html_text(html: str) -> str:
    return _normalize_policy_text(BeautifulSoup(html, "html.parser").get_text(" "))


def _infer_action(html: str) -> str | None:
    decision = _extract_policy_decision(_normalized_html_text(html).lower())
    if decision is None:
        return None
    verb = decision[0]
    if verb in {"maintain", "keep"}:
        return "Hold"
    if verb in {"raise", "increase"}:
        return "Hike"
    return "Cut"


def _infer_vote_split(html: str) -> str | None:
    vote = _infer_vote(html)
    return vote[1] if vote is not None else None


def _infer_vote(html: str) -> tuple[str, str] | None:
    soup = BeautifulSoup(html, "html.parser")
    paragraphs = [
        _normalize_policy_text(paragraph.get_text(" "))
        for paragraph in soup.find_all("p")
        if _normalize_policy_text(paragraph.get_text(" "))
    ]
    if not paragraphs:
        paragraphs = [_normalized_html_text(html)]

    for paragraph in paragraphs:
        if paragraph.startswith("Voting (by notation) for the monetary policy action"):
            prefix = "Voting (by notation) for the monetary policy action were "
            if not paragraph.startswith(prefix) or not paragraph.endswith("."):
                raise NormalizationError("FOMC malformed notation-vote paragraph")
            voters = _parse_named_voters(paragraph[len(prefix) : -1])
            return "stated", f"{len(voters)}-0"

        if paragraph.startswith("Voting for the monetary policy action"):
            return "stated", _parse_regular_vote_paragraph(paragraph)

    compact = _normalized_html_text(html)
    explicit = re.search(
        r"the federal open market committee approved the following statement "
        r"for release by (?:a )?(\d+)\s*-\s*(\d+)\s+vote\b",
        compact,
        flags=re.IGNORECASE,
    )
    if explicit is not None:
        return "stated", f"{explicit.group(1)}-{explicit.group(2)}"
    if re.search(
        r"approved the following statement for release by", compact, re.IGNORECASE
    ):
        raise NormalizationError("FOMC malformed published vote split")
    return None


def _infer_target_range(html: str) -> tuple[Decimal, Decimal] | None:
    compact = _normalized_html_text(html).lower()
    decision = _extract_policy_decision(compact)
    if decision is not None:
        lower_raw, upper_raw = decision[1], decision[2]
    else:
        direct = re.fullmatch(_TARGET_RANGE, compact)
        if direct is None:
            return None
        lower_raw, upper_raw = direct.group("lower"), direct.group("upper")
    try:
        lower = _parse_numeric_token(lower_raw)
        upper = _parse_numeric_token(upper_raw)
        if lower > upper:
            raise ValueError("FOMC target range lower bound exceeds upper bound")
        return lower, upper
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        logger.debug("invalid FOMC target range: %s", repr(exc))
        return None


def _extract_policy_decision(text: str) -> tuple[str, str, str] | None:
    for pattern in _DECISION_PATTERNS:
        match = pattern.search(text)
        if match is not None:
            return match.group("verb"), match.group("lower"), match.group("upper")
    return None


def _parse_numeric_token(raw: str) -> Decimal:
    if re.fullmatch(r"\d+(?:\.\d+)?", raw):
        value = Decimal(raw)
    else:
        mixed = re.fullmatch(r"(?:(\d+)-)?(\d+)/(\d+)", raw)
        if mixed is None:
            raise ValueError(f"malformed FOMC numeric token: {raw!r}")
        denominator = Decimal(mixed.group(3))
        if denominator == 0:
            raise ValueError("FOMC numeric token has zero denominator")
        value = Decimal(mixed.group(2)) / denominator
        if mixed.group(1) is not None:
            value += Decimal(mixed.group(1))
    if not value.is_finite():
        raise ValueError("FOMC numeric token must be finite")
    return value


def _infer_published_at(html: str, meeting_date: date) -> datetime | None:
    compact = _normalized_html_text(html)
    match = re.search(
        r"For release at (\d{1,2}):(\d{2})\s+([ap])\.m\.,?\s+(E[DS]T)",
        compact,
        flags=re.IGNORECASE,
    )
    if match is None:
        return None
    hour = int(match.group(1)) % 12
    if match.group(3).lower() == "p":
        hour += 12
    published = datetime.combine(
        meeting_date,
        time(hour=hour, minute=int(match.group(2))),
        tzinfo=ZoneInfo("America/New_York"),
    )
    if published.tzname() != match.group(4).upper():
        logger.debug(
            "FOMC release timezone mismatch: parsed=%s declared=%s",
            published.tzname(),
            match.group(4).upper(),
        )
        return None
    return published


def _parse_regular_vote_paragraph(paragraph: str) -> str:
    prefix = "Voting for the monetary policy action were "
    if not paragraph.startswith(prefix):
        raise NormalizationError("FOMC malformed monetary-policy voting paragraph")
    body = paragraph[len(prefix) :]
    against_marker = re.search(
        r"\. Voting against (?:this action|the action) (?:was|were) ", body
    )
    if against_marker is None:
        if not body.endswith("."):
            raise NormalizationError(
                "FOMC monetary-policy voter list has no boundary"
            )
        for_raw = body[:-1]
        against_count = 0
    else:
        for_raw = body[: against_marker.start()]
        against_raw = body[against_marker.end() :]
        against_count = len(_parse_against_voters(against_raw))
    for_count = len(_parse_named_voters(for_raw))
    return f"{for_count}-{against_count}"


def _parse_against_voters(raw: str) -> list[str]:
    voters: list[str] = []
    for clause in raw.split(";"):
        bounded = clause.strip()
        rationale = re.search(r",\s+(?:who|each of whom)\b", bounded)
        if rationale is not None:
            names_only = bounded[: rationale.start()]
        else:
            names_only = bounded.removesuffix(".")
        if " and " in names_only:
            names_only = names_only.replace(" and ", "; and ")
        voters.extend(_parse_named_voters(names_only))
    return voters


def _parse_named_voters(raw: str) -> list[str]:
    parts = [part.strip() for part in raw.split(";")]
    if not parts or any(not part for part in parts):
        raise NormalizationError("FOMC empty named voter")
    voters: list[str] = []
    for index, part in enumerate(parts):
        if part.startswith("and "):
            if index != len(parts) - 1:
                raise NormalizationError(
                    "FOMC misplaced conjunction in named voter list"
                )
            part = part[4:].strip()
        if _VOTER_NAME.fullmatch(part) is None:
            raise NormalizationError(f"FOMC malformed named voter: {part!r}")
        voters.append(part)
    if len(set(voters)) != len(voters):
        raise NormalizationError("FOMC duplicate named voter")
    return voters
