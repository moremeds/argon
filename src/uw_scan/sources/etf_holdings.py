"""Daily ETF holdings for the gold complex.

Targets: GLD (SPDR), IAU (BlackRock), GLDM (SPDR), PHYS (Sprott).
Each fund has its own endpoint and payload shape; we normalise to EtfHoldingRow.
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
class EtfHoldingRow:
    ticker: str
    obs_date: date
    holdings_oz: Decimal | None
    shares_out: Decimal | None
    nav_per_share: Decimal | None
    premium_pct: Decimal | None


RecordHook = Callable[["EtfHoldingsProvider", ExternalApiRequestEvent], None]


class EtfHoldingsProvider:
    GLD_URL = "https://www.spdrgoldshares.com/usa/historical-data/"
    GLDM_URL = "https://www.spdrgoldshares.com/usa/historical-data-gldm/"
    IAU_URL = "https://www.ishares.com/us/products/239561/iau-holdings.ajax"
    PHYS_URL = "https://sprott.com/api/v1/funds/phys/nav-history"
    PROVIDER = "etf_holdings"

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

    def __enter__(self) -> "EtfHoldingsProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_gld(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(
            self.GLD_URL, {}, endpoint_key="spdr_gld_csv"
        )
        response.raise_for_status()
        return self._parse_spdr_csv("GLD", response.text, start)

    def fetch_gldm(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(
            self.GLDM_URL, {}, endpoint_key="spdr_gldm_csv"
        )
        response.raise_for_status()
        return self._parse_spdr_csv("GLDM", response.text, start)

    def fetch_iau(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(
            self.IAU_URL, {}, endpoint_key="blackrock_iau"
        )
        response.raise_for_status()
        out: list[EtfHoldingRow] = []
        for row in (response.json() or {}).get("data", []):
            d = _parse_date(row.get("asOfDate"))
            if d is None or (start and d < start):
                continue
            out.append(
                EtfHoldingRow(
                    ticker="IAU",
                    obs_date=d,
                    holdings_oz=_dec(row.get("physicalGoldOunces")),
                    shares_out=None,
                    nav_per_share=_dec(row.get("navPerShare")),
                    premium_pct=None,
                )
            )
        return out

    def fetch_phys(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        response = self._get_with_telemetry(
            self.PHYS_URL, {}, endpoint_key="sprott_phys"
        )
        response.raise_for_status()
        out: list[EtfHoldingRow] = []
        for row in (response.json() or {}).get("data", []):
            d = _parse_date(row.get("date"))
            if d is None or (start and d < start):
                continue
            out.append(
                EtfHoldingRow(
                    ticker="PHYS",
                    obs_date=d,
                    holdings_oz=_dec(row.get("goldOunces")),
                    shares_out=None,
                    nav_per_share=_dec(row.get("nav")),
                    premium_pct=_dec(row.get("premiumDiscountPct")),
                )
            )
        return out

    def _parse_spdr_csv(
        self, ticker: str, text: str, start: date | None
    ) -> list[EtfHoldingRow]:
        out: list[EtfHoldingRow] = []
        reader = csv.DictReader(io.StringIO(text))
        for row in reader:
            d = _parse_date(row.get("Date"))
            if d is None or (start and d < start):
                continue
            out.append(
                EtfHoldingRow(
                    ticker=ticker,
                    obs_date=d,
                    holdings_oz=_dec(row.get("Ounces in the Trust")),
                    shares_out=None,
                    nav_per_share=_dec(row.get("NAV per Share (USD)")),
                    premium_pct=None,
                )
            )
        return out

    def _get_with_telemetry(
        self, url: str, params: dict[str, Any], *, endpoint_key: str
    ) -> httpx.Response:
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(url, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                self._build_event(
                    url,
                    params,
                    endpoint_key,
                    started_at,
                    finished_at,
                    status_code=None,
                    error_message=repr(exc)[:1000],
                )
            )
            raise
        finished_at = datetime.now(UTC)
        self._record_request(
            self._build_event(
                url,
                params,
                endpoint_key,
                started_at,
                finished_at,
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
            logger.debug("etf_holdings telemetry %r", event)

    def _build_event(
        self,
        url: str,
        params: dict[str, Any],
        endpoint_key: str,
        started_at: datetime,
        finished_at: datetime,
        *,
        status_code: int | None,
        error_message: str | None,
    ) -> ExternalApiRequestEvent:
        return ExternalApiRequestEvent(
            provider=self.PROVIDER,
            endpoint_key=endpoint_key,
            method="GET",
            path=url,
            path_template=url,
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


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    raw = raw.strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue
    return None


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None
