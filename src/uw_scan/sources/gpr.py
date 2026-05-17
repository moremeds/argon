"""Caldara-Iacoviello Geopolitical Risk Index (GPRD).

Source: matteoiacoviello.com — free academic CSV.
Persists to uw_scan.macro_series_daily with series_id='GPRD'.
"""

from __future__ import annotations

import csv
import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GprObservation:
    obs_date: date
    value: Decimal


RecordHook = Callable[["GprProvider", ExternalApiRequestEvent], None]


class GprProvider:
    """HTTP fetcher for the daily GPR CSV published by Caldara-Iacoviello."""

    DEFAULT_URL = "https://www.matteoiacoviello.com/gpr_files/gpr_daily_recent.csv"
    ENDPOINT_PATH = "/gpr_files/gpr_daily_recent.csv"
    ENDPOINT_KEY = "gpr_daily_csv"
    PROVIDER = "gpr"

    def __init__(
        self,
        *,
        url: str | None = None,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
    ):
        self._url = url or self.DEFAULT_URL
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "GprProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_daily(self, *, start: date | None = None) -> list[GprObservation]:
        response = self._get_with_telemetry(self._url, {})
        response.raise_for_status()
        rows: list[GprObservation] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            raw_date = (row.get("date") or row.get("DATE") or "").strip()
            raw_val = (row.get("GPRD") or row.get("gprd") or "").strip()
            if not raw_date or not raw_val:
                continue
            try:
                d = date.fromisoformat(raw_date)
                v = Decimal(raw_val)
            except (ValueError, InvalidOperation) as exc:
                logger.warning("gpr: skip unparseable row %r (%s)", row, repr(exc))
                continue
            if start is not None and d < start:
                continue
            rows.append(GprObservation(obs_date=d, value=v))
        return rows

    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._build_event(
                    started_at,
                    finished_at,
                    params,
                    status_code=None,
                    error_message=repr(exc)[:1000],
                )
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._build_event(
                started_at,
                finished_at,
                params,
                status_code=response.status_code,
                error_message=(
                    response.text[:1000] if response.status_code >= 400 else None
                ),
            )
        )
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("gpr telemetry %r", event)

    def _build_event(
        self,
        started_at: datetime,
        finished_at: datetime,
        params: dict[str, Any],
        *,
        status_code: int | None,
        error_message: str | None,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            method="GET",
            path=self.ENDPOINT_PATH,
            path_template=self.ENDPOINT_PATH,
            params=redact_params(params),
            status_code=status_code,
            status_family=status_family_for(
                status_code, transport_error=status_code is None
            ),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            error_message=error_message,
        )
