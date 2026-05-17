"""Caldara-Iacoviello Geopolitical Risk Index (GPRD).

Source: matteoiacoviello.com — free academic dataset.
The publisher switched the daily file from CSV to .xls (BIFF8) in 2024;
the previous /gpr_files/gpr_daily_recent.csv path 404s.

Persists to uw_scan.macro_series_daily with series_id='GPRD'.
"""

from __future__ import annotations

import io
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
import xlrd

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GprObservation:
    obs_date: date
    value: Decimal


RecordHook = Callable[["GprProvider", ExternalApiRequestEvent], None]


class GprProvider:
    """HTTP fetcher for the daily GPR .xls published by Caldara-Iacoviello."""

    DEFAULT_URL = "https://www.matteoiacoviello.com/gpr_files/data_gpr_daily_recent.xls"
    ENDPOINT_PATH = "/gpr_files/data_gpr_daily_recent.xls"
    ENDPOINT_KEY = "gpr_daily_xls"
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
        workbook = xlrd.open_workbook(file_contents=response.content)
        sheet = workbook.sheet_by_index(0)
        if sheet.nrows < 2:
            return []
        header = [str(sheet.cell_value(0, c)).strip() for c in range(sheet.ncols)]
        try:
            day_col = header.index("DAY")
            gprd_col = header.index("GPRD")
        except ValueError as exc:
            logger.warning("gpr: header missing DAY/GPRD columns: %r", repr(exc))
            return []
        rows: list[GprObservation] = []
        for r in range(1, sheet.nrows):
            raw_day = sheet.cell_value(r, day_col)
            raw_val = sheet.cell_value(r, gprd_col)
            parsed_date = _parse_day(raw_day)
            parsed_value = _parse_value(raw_val)
            if parsed_date is None or parsed_value is None:
                continue
            if start is not None and parsed_date < start:
                continue
            rows.append(GprObservation(obs_date=parsed_date, value=parsed_value))
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


def _parse_day(raw: object) -> date | None:
    """Coerce the DAY column (YYYYMMDD as int or string) to a date."""
    if raw is None or raw == "":
        return None
    try:
        if isinstance(raw, (int, float)):
            s = str(int(raw))
        else:
            s = str(raw).strip()
        if len(s) != 8:
            return None
        return date(int(s[0:4]), int(s[4:6]), int(s[6:8]))
    except (ValueError, TypeError) as exc:
        logger.debug("gpr: unparseable DAY %r (%s)", raw, repr(exc))
        return None


def _parse_value(raw: object) -> Decimal | None:
    """Coerce the GPRD column (float or string) to a Decimal."""
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw))
    except (InvalidOperation, ValueError) as exc:
        logger.debug("gpr: unparseable GPRD %r (%s)", raw, repr(exc))
        return None
