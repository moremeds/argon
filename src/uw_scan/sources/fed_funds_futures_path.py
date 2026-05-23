"""Fed funds futures implied policy path source.

FedChirp publishes a daily path table derived from fed funds futures using
FedWatch-style step-path math. We use it as a free/delayed alternative to the
paid CME FedWatch probability API and label it as third-party futures-derived
data throughout the rates dashboard.
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from html.parser import HTMLParser
from typing import Literal

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import status_family_for

logger = logging.getLogger(__name__)

PathStance = Literal["CUT", "HOLD", "HIKE", "UNKNOWN"]


@dataclass(frozen=True)
class FedFundsFuturesPathPoint:
    meeting_date: date
    label: str
    probability: float
    stance: PathStance
    target_range: str | None
    implied_rate: Decimal | None = None
    source: str = "FedChirp fed funds futures"

    def to_payload(self) -> dict[str, object]:
        return {
            "meeting_date": self.meeting_date,
            "label": self.label,
            "probability": self.probability,
            "stance": self.stance,
            "target_range": self.target_range,
            "source": self.source,
            "status": "ok",
        }


RecordHook = Callable[["FedChirpPolicyPathProvider", ExternalApiRequestEvent], None]


class FedChirpPolicyPathProvider:
    BASE_URL = "https://www.fedchirp.com"
    PATH = "/"
    PROVIDER = "fedchirp"
    ENDPOINT_KEY = "fed_funds_futures_path"

    def __init__(
        self,
        *,
        base_url: str = BASE_URL,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
        job_name: str | None = None,
    ):
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s, follow_redirects=True)
        self._record_request_fn = record_request
        self._job_name = job_name

    def __enter__(self) -> "FedChirpPolicyPathProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_latest_path(
        self, *, current_target_range: str | None
    ) -> list[FedFundsFuturesPathPoint]:
        response = self._get()
        response.raise_for_status()
        current_range = _target_range(current_target_range)
        rows = _FedChirpPathParser().parse(response.text)
        out: list[FedFundsFuturesPathPoint] = []
        for row in rows:
            best = _best_probability_bucket(row.probabilities)
            if best is None:
                continue
            stance, step_bps = _stance_and_step(best[0])
            out.append(
                FedFundsFuturesPathPoint(
                    meeting_date=row.meeting_date,
                    label=f"{row.meeting_date.month}/{row.meeting_date.day}",
                    probability=round(float(best[1]), 1),
                    stance=stance,
                    target_range=_shift_target_range(current_range, step_bps),
                    implied_rate=row.implied_rate,
                )
            )
        return out

    def _get(self) -> httpx.Response:
        started_at = datetime.now(UTC)
        path = self.PATH
        try:
            response = self._client.get(f"{self._base_url}{path}")
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._event(
                    path,
                    started_at,
                    finished_at,
                    status_code=None,
                    error_message=str(exc),
                )
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._event(
                path,
                started_at,
                finished_at,
                status_code=response.status_code,
                error_message=None,
            )
        )
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("fedchirp telemetry %r", event)

    def _event(
        self,
        path: str,
        started_at: datetime,
        finished_at: datetime,
        *,
        status_code: int | None,
        error_message: str | None,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            method="GET",
            path=path,
            path_template=path,
            params={},
            status_code=status_code,
            status_family=status_family_for(
                status_code, transport_error=status_code is None
            ),
            latency_ms=max((finished_at - started_at).total_seconds() * 1000, 0),
            error_message=error_message,
            started_at=started_at,
            finished_at=finished_at,
            job_name=self._job_name,
        )


@dataclass(frozen=True)
class _ParsedPathRow:
    meeting_date: date
    implied_rate: Decimal | None
    probabilities: dict[str, Decimal]


class _FedChirpPathParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._in_path_section = False
        self._in_row = False
        self._cell_label: str | None = None
        self._cell_parts: list[str] = []
        self._current: dict[str, str] = {}
        self.rows: list[_ParsedPathRow] = []

    def parse(self, html: str) -> list[_ParsedPathRow]:
        self.feed(html)
        return self.rows

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = dict(attrs)
        if tag == "h3" and attr.get("class") == "path__h3":
            self._in_path_section = True
            return
        if not self._in_path_section:
            return
        if tag == "tr":
            self._in_row = True
            self._current = {}
            return
        if self._in_row and tag in {"td", "th"}:
            self._cell_label = attr.get("data-label")
            self._cell_parts = []

    def handle_data(self, data: str) -> None:
        if self._cell_label is not None:
            self._cell_parts.append(data)

    def handle_endtag(self, tag: str) -> None:
        if self._in_row and tag in {"td", "th"} and self._cell_label is not None:
            text = " ".join(part.strip() for part in self._cell_parts if part.strip())
            self._current[self._cell_label] = text
            self._cell_label = None
            self._cell_parts = []
            return
        if self._in_row and tag == "tr":
            row = _row_from_cells(self._current)
            if row is not None:
                self.rows.append(row)
            self._current = {}
            self._in_row = False
            return
        if self._in_path_section and tag == "table":
            self._in_path_section = False


def _row_from_cells(cells: dict[str, str]) -> _ParsedPathRow | None:
    raw_meeting = cells.get("Meeting")
    if raw_meeting is None:
        return None
    try:
        meeting_date = date.fromisoformat(raw_meeting)
    except ValueError:
        return None
    probabilities = {
        label: probability
        for label, probability in (
            (key, _parse_percent(value))
            for key, value in cells.items()
            if key.startswith("Cut ") or key == "Hold" or key.startswith("Hike ")
        )
        if probability is not None
    }
    return _ParsedPathRow(
        meeting_date=meeting_date,
        implied_rate=_parse_percent(cells.get("Implied rate after")),
        probabilities=probabilities,
    )


def _parse_percent(raw: str | None) -> Decimal | None:
    if raw is None:
        return None
    match = re.search(r"[-+]?\d+(?:\.\d+)?", raw.replace(",", ""))
    if match is None:
        return None
    try:
        return Decimal(match.group(0))
    except InvalidOperation:
        return None


def _best_probability_bucket(
    probabilities: dict[str, Decimal]
) -> tuple[str, Decimal] | None:
    if not probabilities:
        return None
    return max(probabilities.items(), key=lambda item: item[1])


def _stance_and_step(label: str) -> tuple[PathStance, Decimal]:
    if label == "Hold":
        return "HOLD", Decimal("0")
    match = re.fullmatch(r"(Cut|Hike)\s+(\d+)\s+bp", label)
    if match is None:
        return "UNKNOWN", Decimal("0")
    step = Decimal(match.group(2)) / Decimal(100)
    if match.group(1) == "Cut":
        return "CUT", -step
    return "HIKE", step


def _target_range(raw: str | None) -> tuple[Decimal, Decimal] | None:
    if raw is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", raw)
    if match is None:
        return None
    try:
        return Decimal(match.group(1)), Decimal(match.group(2))
    except InvalidOperation:
        return None


def _shift_target_range(
    target_range: tuple[Decimal, Decimal] | None, step: Decimal
) -> str | None:
    if target_range is None:
        return None
    lower, upper = target_range
    return f"{lower + step:.2f}-{upper + step:.2f}%"
