"""Federal Reserve FOMC calendar and statement source."""

from __future__ import annotations

import calendar
import logging
import re
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, datetime, time
from decimal import Decimal, InvalidOperation
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

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
        self._client = httpx.Client(timeout=timeout_s, follow_redirects=True)

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


def _infer_action(html: str) -> str | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    lowered = " ".join(text.lower().split())
    if "maintain the target range" in lowered:
        return "Hold"
    if "lower the target range" in lowered or "lowered the target range" in lowered:
        return "Cut"
    if "raise the target range" in lowered or "raised the target range" in lowered:
        return "Hike"
    return None


def _infer_vote_split(html: str) -> str | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    compact = " ".join(text.split())
    explicit = re.search(
        r"approved .*? by (?:a )?(\d+)\s*[\-–—]\s*(\d+)\s+vote",
        compact,
        flags=re.IGNORECASE,
    )
    if explicit is not None:
        return f"{explicit.group(1)}-{explicit.group(2)}"
    for_match = re.search(
        r"Voting for .*? were (.*?)(?:\. Voting against|\.?$)",
        compact,
        flags=re.IGNORECASE,
    )
    against_match = re.search(
        r"Voting against .*? were (.*)$",
        compact,
        flags=re.IGNORECASE,
    )
    if for_match is None:
        return None
    for_count = _count_names(for_match.group(1))
    against_count = _count_names(against_match.group(1)) if against_match else 0
    if for_count == 0:
        return None
    return f"{for_count}-{against_count}"


def _infer_target_range(html: str) -> tuple[Decimal, Decimal] | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    compact = " ".join(text.lower().split())
    match = re.search(
        r"target range for the federal funds rate at "
        r"(\d+(?:\.\d+)?(?:-\d+/\d+)?)\s+to\s+"
        r"(\d+(?:\.\d+)?(?:-\d+/\d+)?)\s+percent",
        compact,
    )
    if match is None:
        return None
    try:
        return _mixed_decimal(match.group(1)), _mixed_decimal(match.group(2))
    except (InvalidOperation, ValueError, ZeroDivisionError) as exc:
        logger.debug("invalid FOMC target range: %s", repr(exc))
        return None


def _mixed_decimal(raw: str) -> Decimal:
    if "-" not in raw:
        return Decimal(raw)
    whole, fraction = raw.split("-", 1)
    numerator, denominator = fraction.split("/", 1)
    return Decimal(whole) + Decimal(numerator) / Decimal(denominator)


def _infer_published_at(html: str, meeting_date: date) -> datetime | None:
    text = BeautifulSoup(html, "html.parser").get_text(" ")
    compact = " ".join(text.split())
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


def _count_names(text: str) -> int:
    names = re.findall(r"\b[A-Z][a-z]+(?:\s+[A-Z]\.)?\s+[A-Z][a-z]+\b", text)
    if names:
        return len(names)
    normalized = re.sub(r"\band\b", ",", text, flags=re.IGNORECASE)
    return len([part for part in normalized.split(",") if part.strip()])
