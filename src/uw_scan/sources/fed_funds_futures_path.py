"""Fed funds futures implied policy path source.

Frenzy Capital publishes an SSR JSON snapshot of fed-funds-futures move
probabilities. We use it as a free/delayed alternative to the paid CME FedWatch
API and label it as third-party futures-derived data throughout the rates
dashboard.
"""

from __future__ import annotations

import json
import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
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
    source: str = "Frenzy Capital Fed Watch"

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


RecordHook = Callable[["FedFundsFuturesPathProvider", ExternalApiRequestEvent], None]


class FedFundsFuturesPathProvider:
    BASE_URL = "https://www.frenzycap.com/fedwatch"
    PATH = ""
    PROVIDER = "frenzy_capital"
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

    def __enter__(self) -> "FedFundsFuturesPathProvider":
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
        rows = _FrenzyFedWatchParser().parse(response.text)
        if not rows:
            raise ValueError("Frenzy Fed Watch payload did not contain meeting rows")
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
                    probability=round(float(best[1] * Decimal(100)), 1),
                    stance=stance,
                    target_range=_shift_target_range(current_range, step_bps),
                    implied_rate=row.implied_rate,
                )
            )
        if not out:
            raise ValueError("Frenzy Fed Watch payload did not contain probabilities")
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
            logger.debug("fed funds futures path telemetry %r", event)

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


class _FrenzyFedWatchParser:
    _DATA_RE = re.compile(r"window\.__SSR_DATA__\s*=\s*(\{.*?\});\s*</script>", re.S)

    def parse(self, html: str) -> list[_ParsedPathRow]:
        match = self._DATA_RE.search(html)
        if match is None:
            return []
        try:
            payload = json.loads(match.group(1))
        except json.JSONDecodeError:
            return []

        rows: list[_ParsedPathRow] = []
        for item in payload.get("meetings", []):
            if not isinstance(item, dict):
                continue
            row = _row_from_frenzy_meeting(item)
            if row is not None:
                rows.append(row)
        return rows


def _row_from_frenzy_meeting(item: dict[str, object]) -> _ParsedPathRow | None:
    raw_meeting = item.get("meeting_date")
    if not isinstance(raw_meeting, str):
        return None
    try:
        meeting_date = date.fromisoformat(raw_meeting)
    except ValueError:
        return None

    raw_probabilities = item.get("probabilities")
    if not isinstance(raw_probabilities, dict):
        return None
    probabilities = {
        label: probability
        for label, probability in (
            (_probability_label(key), _parse_decimal(value))
            for key, value in raw_probabilities.items()
        )
        if label is not None and probability is not None
    }
    return _ParsedPathRow(
        meeting_date=meeting_date,
        implied_rate=_parse_decimal(item.get("post_rate")),
        probabilities=probabilities,
    )


def _probability_label(key: object) -> str | None:
    labels = {
        "cut_gt25": "Cut 50 bp",
        "cut_25": "Cut 25 bp",
        "hold": "Hold",
        "hike_25": "Hike 25 bp",
        "hike_gt25": "Hike 50 bp",
    }
    return labels.get(key)


def _parse_decimal(raw: object) -> Decimal | None:
    if raw is None:
        return None
    if isinstance(raw, str):
        match = re.search(r"[-+]?\d+(?:\.\d+)?", raw.replace(",", ""))
        if match is None:
            return None
        raw = match.group(0)
    try:
        return Decimal(str(raw))
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
