"""CME FedWatch API source for FOMC implied path probabilities."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx


@dataclass(frozen=True)
class CmeFedWatchPathPoint:
    meeting_date: date
    label: str
    probability: float
    stance: str
    target_range: str
    source: str = "CME FedWatch"

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


class CmeFedWatchProvider:
    BASE_URL = "https://markets.api.cmegroup.com/fedwatch/v1"
    LATEST_FORECAST_PATH = "/forecasts/latest"

    def __init__(
        self,
        *,
        api_token: str,
        application_name: str = "uw-scan",
        base_url: str = BASE_URL,
        timeout_s: float = 30.0,
    ):
        self._api_token = api_token
        self._application_name = application_name
        self._base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s, follow_redirects=True)

    def __enter__(self) -> "CmeFedWatchProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def close(self) -> None:
        self._client.close()

    def fetch_latest_path(
        self, *, current_target_range: str | None
    ) -> list[CmeFedWatchPathPoint]:
        response = self._get(self.LATEST_FORECAST_PATH)
        response.raise_for_status()
        current_mid = _target_midpoint(current_target_range)
        rows: list[CmeFedWatchPathPoint] = []
        for meeting in _iter_meetings(response.json()):
            meeting_date = _parse_date(
                meeting.get("meetingDate")
                or meeting.get("meeting_date")
                or meeting.get("meetingDt")
                or meeting.get("date")
            )
            if meeting_date is None:
                continue
            probabilities = list(_iter_probabilities(meeting))
            if not probabilities:
                continue
            target_range, probability = max(probabilities, key=lambda item: item[1])
            rows.append(
                CmeFedWatchPathPoint(
                    meeting_date=meeting_date,
                    label=f"{meeting_date.month}/{meeting_date.day}",
                    probability=round(float(probability), 1),
                    stance=_stance(target_range, current_mid),
                    target_range=target_range,
                )
            )
        return rows

    def _get(self, path: str) -> httpx.Response:
        return self._client.get(
            f"{self._base_url}{path}",
            headers={
                "Authorization": f"Bearer {self._api_token}",
                "CME-Application-Name": self._application_name,
                "Accept": "application/json",
            },
        )


def _iter_meetings(payload: dict[str, Any]):
    meetings = payload.get("meetings") or payload.get("data") or payload.get("forecasts")
    if isinstance(meetings, list):
        yield from (item for item in meetings if isinstance(item, dict))


def _iter_probabilities(meeting: dict[str, Any]):
    values = (
        meeting.get("probabilities")
        or meeting.get("rateProbabilities")
        or meeting.get("rateRange")
        or []
    )
    if not isinstance(values, list):
        return
    for row in values:
        if not isinstance(row, dict):
            continue
        raw_range = _row_target_range(row)
        probability = row.get("probability") or row.get("probabilityPercent")
        target_range = _format_target_range(raw_range)
        if target_range is None or probability is None:
            continue
        yield target_range, Decimal(str(probability))


def _parse_date(raw: object) -> date | None:
    if raw is None:
        return None
    try:
        return date.fromisoformat(str(raw)[:10])
    except ValueError:
        return None


def _row_target_range(row: dict[str, Any]) -> object:
    lower = row.get("lowerRt")
    upper = row.get("upperRt")
    if lower is not None and upper is not None:
        return f"{lower}-{upper}"
    return (
        row.get("targetRate")
        or row.get("target_rate")
        or row.get("targetRange")
        or row.get("rateRange")
    )


def _format_target_range(raw: object) -> str | None:
    if raw is None:
        return None
    text = str(raw).strip()
    match = re.fullmatch(r"(\d{2,3})[-/](\d{2,3})", text)
    if match:
        lower = Decimal(match.group(1)) / Decimal(100)
        upper = Decimal(match.group(2)) / Decimal(100)
        return f"{lower:.2f}-{upper:.2f}%"
    return text if "%" in text else None


def _target_midpoint(target_range: str | None) -> Decimal | None:
    if target_range is None:
        return None
    match = re.search(r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)", target_range)
    if match is None:
        return None
    try:
        return (Decimal(match.group(1)) + Decimal(match.group(2))) / Decimal(2)
    except InvalidOperation:
        return None


def _stance(target_range: str, current_mid: Decimal | None) -> str:
    target_mid = _target_midpoint(target_range)
    if target_mid is None or current_mid is None:
        return "UNKNOWN"
    if target_mid < current_mid:
        return "CUT"
    if target_mid > current_mid:
        return "HIKE"
    return "HOLD"
