"""FRED CSV provider for daily and monthly macro series.

Reference source pattern for the other Phase A1 (Gold) sources.

Returns typed dataclasses; persistence is the caller's responsibility.
Telemetry records every request via the `ExternalApiRequestEvent` shape
expected by `ExternalApiRequestRecorder`. A `record_request` callable
hook is exposed for tests; production wires the recorder.
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
class FredObservation:
    series_id: str
    obs_date: date
    value: Decimal


RecordHook = Callable[["FredProvider", ExternalApiRequestEvent], None]


class FredProvider:
    """REST client for the FRED CSV endpoint.

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
    No auth required; the daily worker uses this for full-series refresh.
    """

    BASE_URL = "https://fred.stlouisfed.org"
    ENDPOINT_PATH = "/graph/fredgraph.csv"
    ENDPOINT_KEY = "fred_csv"
    PROVIDER = "fred"

    def __init__(
        self,
        *,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
    ):
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "FredProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_series(
        self, series_id: str, *, start: date | None = None
    ) -> list[FredObservation]:
        params: dict[str, Any] = {"id": series_id}
        response = self._get_with_telemetry(self.ENDPOINT_PATH, params)
        response.raise_for_status()
        out: list[FredObservation] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            raw_date = row.get("observation_date") or row.get("DATE")
            raw_val = row.get(series_id) or row.get(series_id.upper())
            if raw_date is None or raw_val is None or raw_val.strip() == ".":
                continue
            try:
                d = date.fromisoformat(raw_date.strip())
                v = Decimal(raw_val.strip())
            except (ValueError, InvalidOperation) as exc:
                logger.warning("fred: skip unparseable row %r (%s)", row, repr(exc))
                continue
            if start is not None and d < start:
                continue
            out.append(FredObservation(series_id=series_id, obs_date=d, value=v))
        return out

    def _get_with_telemetry(self, path: str, params: dict[str, Any]) -> httpx.Response:
        url = f"{self.BASE_URL}{path}"
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._error_event(path, params, started_at, finished_at, exc)
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._success_event(path, params, started_at, finished_at, response)
        )
        return response

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("fred telemetry %r", event)

    def _success_event(
        self,
        path: str,
        params: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        response: httpx.Response,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            method="GET",
            path=path,
            path_template=self.ENDPOINT_PATH,
            params=redact_params(params),
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=_latency_ms(started_at, finished_at),
            error_message=(
                response.text[:1000] if response.status_code >= 400 else None
            ),
        )

    def _error_event(
        self,
        path: str,
        params: dict[str, Any],
        started_at: datetime,
        finished_at: datetime,
        exc: httpx.HTTPError,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            method="GET",
            path=path,
            path_template=self.ENDPOINT_PATH,
            params=redact_params(params),
            status_code=None,
            status_family=status_family_for(None, transport_error=True),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=_latency_ms(started_at, finished_at),
            error_message=repr(exc)[:1000],
        )


def _latency_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, int((finished_at - started_at).total_seconds() * 1000))
