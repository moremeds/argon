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
    realtime_start: date | None = None
    realtime_end: date | None = None


RecordHook = Callable[["FredProvider", ExternalApiRequestEvent], None]


class FredProvider:
    """REST client for FRED CSV and official JSON observation endpoints.

    https://fred.stlouisfed.org/graph/fredgraph.csv?id=<SERIES_ID>
    https://api.stlouisfed.org/fred/series/observations

    The CSV path remains no-auth for the existing Gold ingestion. New rates
    ingestion uses the official JSON API with FRED_API_KEY.
    """

    CSV_BASE_URL = "https://fred.stlouisfed.org"
    CSV_ENDPOINT_PATH = "/graph/fredgraph.csv"
    CSV_ENDPOINT_KEY = "fred_csv"
    API_BASE_URL = "https://api.stlouisfed.org"
    API_ENDPOINT_PATH = "/fred/series/observations"
    API_ENDPOINT_KEY = "fred_series_observations"
    PROVIDER = "fred"

    def __init__(
        self,
        *,
        api_key: str | None = None,
        base_url: str = API_BASE_URL,
        timeout_s: float = 30.0,
        record_request: RecordHook | None = None,
        job_name: str | None = None,
    ):
        self._api_key = api_key
        self._api_base_url = base_url.rstrip("/")
        self._client = httpx.Client(timeout=timeout_s)
        self._record_request_fn = record_request
        self._job_name = job_name

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
        response = self._get_with_telemetry(
            self.CSV_BASE_URL,
            self.CSV_ENDPOINT_PATH,
            params,
            endpoint_key=self.CSV_ENDPOINT_KEY,
            path_template=self.CSV_ENDPOINT_PATH,
        )
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

    def fetch_observations(
        self,
        series_id: str,
        *,
        start: date | None = None,
        end: date | None = None,
    ) -> list[FredObservation]:
        """Fetch observations from the official FRED JSON API."""
        if not self._api_key:
            raise RuntimeError("FRED API key is required for JSON observations")
        params: dict[str, Any] = {
            "series_id": series_id,
            "file_type": "json",
            "api_key": self._api_key,
        }
        if start is not None:
            params["observation_start"] = start.isoformat()
        if end is not None:
            params["observation_end"] = end.isoformat()
        response = self._get_with_telemetry(
            self._api_base_url,
            self.API_ENDPOINT_PATH,
            params,
            endpoint_key=self.API_ENDPOINT_KEY,
            path_template=self.API_ENDPOINT_PATH,
        )
        response.raise_for_status()
        payload = response.json()
        out: list[FredObservation] = []
        for row in payload.get("observations", []):
            raw_date = row.get("date")
            raw_val = row.get("value")
            if raw_date is None or raw_val is None or str(raw_val).strip() == ".":
                continue
            try:
                obs_date = date.fromisoformat(str(raw_date).strip())
                value = Decimal(str(raw_val).strip())
                realtime_start = date.fromisoformat(str(row["realtime_start"]).strip())
                realtime_end = date.fromisoformat(str(row["realtime_end"]).strip())
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.warning("fred: skip unparseable json row %r (%s)", row, repr(exc))
                continue
            out.append(
                FredObservation(
                    series_id=series_id,
                    obs_date=obs_date,
                    value=value,
                    realtime_start=realtime_start,
                    realtime_end=realtime_end,
                )
            )
        return out

    def _get_with_telemetry(
        self,
        base_url: str,
        path: str,
        params: dict[str, Any],
        *,
        endpoint_key: str,
        path_template: str,
    ) -> httpx.Response:
        url = f"{base_url}{path}"
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._error_event(
                    path,
                    params,
                    started_at,
                    finished_at,
                    exc,
                    endpoint_key=endpoint_key,
                    path_template=path_template,
                )
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._success_event(
                path,
                params,
                started_at,
                finished_at,
                response,
                endpoint_key=endpoint_key,
                path_template=path_template,
            )
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
        *,
        endpoint_key: str,
        path_template: str,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=endpoint_key,
            method="GET",
            path=path,
            path_template=path_template,
            params=redact_params(params),
            status_code=response.status_code,
            status_family=status_family_for(response.status_code),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=_latency_ms(started_at, finished_at),
            job_name=self._job_name,
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
        *,
        endpoint_key: str,
        path_template: str,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=endpoint_key,
            method="GET",
            path=path,
            path_template=path_template,
            params=redact_params(params),
            status_code=None,
            status_family=status_family_for(None, transport_error=True),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=_latency_ms(started_at, finished_at),
            job_name=self._job_name,
            error_message=repr(exc)[:1000],
        )


def _latency_ms(started_at: datetime, finished_at: datetime) -> int:
    return max(0, int((finished_at - started_at).total_seconds() * 1000))
