"""LBMA monthly vault holdings (loco London).

Source: https://www.lbma.org.uk/prices-and-data/vault-holdings-data
CSV columns include Date, Gold (oz), Silver (oz). We use Gold (oz).
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
class LbmaVaultRow:
    obs_date: date
    vault_oz: Decimal | None


RecordHook = Callable[["LbmaProvider", ExternalApiRequestEvent], None]


class LbmaProvider:
    URL = "https://www.lbma.org.uk/prices-and-data/vault-holdings-data.csv"
    ENDPOINT_PATH = "/prices-and-data/vault-holdings-data.csv"
    ENDPOINT_KEY = "lbma_vault_csv"
    PROVIDER = "lbma"

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

    def __enter__(self) -> "LbmaProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_monthly(self, *, start: date | None = None) -> list[LbmaVaultRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[LbmaVaultRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            raw_date = (row.get("Date") or "").strip()
            raw_oz = (row.get("Gold (oz)") or row.get("Gold oz") or "").strip()
            if not raw_date or not raw_oz:
                continue
            try:
                d = date.fromisoformat(raw_date)
                v = Decimal(raw_oz.replace(",", ""))
            except (ValueError, InvalidOperation):
                continue
            if start and d < start:
                continue
            out.append(LbmaVaultRow(obs_date=d, vault_oz=v))
        return out

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
            logger.debug("lbma telemetry %r", event)

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
