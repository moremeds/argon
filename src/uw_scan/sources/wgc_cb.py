"""World Gold Council monthly central-bank gold reserves.

Source: gold.org/goldhub/data/monthly-central-bank-statistics
CSV columns observed: Country, Month, Tonnes, Reported, Estimated.
ISO3 mapping in COUNTRY_ISO3 — extend as new countries appear.
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

from uw_scan.cards.cb_buckets import classify_bucket
from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)

COUNTRY_ISO3 = {
    "china": "CHN",
    "india": "IND",
    "russia": "RUS",
    "russian federation": "RUS",
    "turkey": "TUR",
    "türkiye": "TUR",
    "poland": "POL",
    "czech republic": "CZE",
    "czechia": "CZE",
    "singapore": "SGP",
    "hungary": "HUN",
    "qatar": "QAT",
    "philippines": "PHL",
    "thailand": "THA",
    "mexico": "MEX",
    "brazil": "BRA",
    "argentina": "ARG",
    "germany": "DEU",
    "france": "FRA",
    "italy": "ITA",
    "japan": "JPN",
    "united kingdom": "GBR",
    "uk": "GBR",
    "united states": "USA",
    "us": "USA",
    "switzerland": "CHE",
    "netherlands": "NLD",
    "egypt": "EGY",
    "kazakhstan": "KAZ",
    "azerbaijan": "AZE",
}


@dataclass(frozen=True)
class CbReserveRow:
    country_iso3: str
    obs_month: date
    reserves_t: Decimal | None
    bucket: str
    is_reported: bool
    is_estimated: bool


RecordHook = Callable[["WgcCbProvider", ExternalApiRequestEvent], None]


class WgcCbProvider:
    URL = "https://www.gold.org/goldhub/data/monthly-central-bank-statistics.csv"
    ENDPOINT_PATH = "/goldhub/data/monthly-central-bank-statistics.csv"
    ENDPOINT_KEY = "wgc_cb_monthly_csv"
    PROVIDER = "wgc_cb"

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

    def __enter__(self) -> "WgcCbProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_monthly(self, *, start: date | None = None) -> list[CbReserveRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[CbReserveRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            country = (row.get("Country") or "").strip().lower()
            iso3 = COUNTRY_ISO3.get(country)
            if iso3 is None:
                logger.debug("wgc_cb: unknown country %r, skipping", country)
                continue
            month_raw = (row.get("Month") or "").strip()
            tonnes_raw = (row.get("Tonnes") or "").strip()
            try:
                if len(month_raw) == 7:
                    obs_month = date.fromisoformat(month_raw + "-01")
                else:
                    obs_month = date.fromisoformat(month_raw)
                reserves_t = (
                    Decimal(tonnes_raw.replace(",", "")) if tonnes_raw else None
                )
            except (ValueError, InvalidOperation):
                continue
            if start and obs_month < start:
                continue
            is_reported = (row.get("Reported") or "").strip().lower() in (
                "true",
                "1",
                "yes",
            )
            is_estimated = (row.get("Estimated") or "").strip().lower() in (
                "true",
                "1",
                "yes",
            )
            out.append(
                CbReserveRow(
                    country_iso3=iso3,
                    obs_month=obs_month,
                    reserves_t=reserves_t,
                    bucket=classify_bucket(iso3),
                    is_reported=is_reported,
                    is_estimated=is_estimated,
                )
            )
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
            logger.debug("wgc_cb telemetry %r", event)

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
