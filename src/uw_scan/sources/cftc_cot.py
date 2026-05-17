"""CFTC Commitments of Traders (disaggregated) for COMEX gold futures.

Source: cftc.gov public reports / API.
We persist managed-money longs/shorts/net, commercials longs/shorts/net, OI.

Note: CFTC_GOLD_DISAGG_URL is a placeholder; the worker job must pin the actual
disaggregated gold (commodity code 088691) endpoint before being scheduled.
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

CFTC_GOLD_DISAGG_URL = (
    # Placeholder — replace with the disaggregated gold endpoint at install time.
    "https://www.cftc.gov/dea/newcot/FinFutWk.txt"
)


@dataclass(frozen=True)
class CotRow:
    obs_date: date
    release_date: date
    mm_long: Decimal | None
    mm_short: Decimal | None
    mm_net: Decimal | None
    comm_long: Decimal | None
    comm_short: Decimal | None
    comm_net: Decimal | None
    open_interest: Decimal | None


RecordHook = Callable[["CftcCotProvider", ExternalApiRequestEvent], None]


class CftcCotProvider:
    URL = CFTC_GOLD_DISAGG_URL
    ENDPOINT_PATH = "/dea/newcot/FinFutWk.txt"
    ENDPOINT_KEY = "cftc_cot_disagg_csv"
    PROVIDER = "cftc_cot"

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

    def __enter__(self) -> "CftcCotProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_weekly(self, *, start: date | None = None) -> list[CotRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[CotRow] = []
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            try:
                obs = date.fromisoformat(row["Report_Date_as_YYYY-MM-DD"])
                rel = date.fromisoformat(row["Report_Date_as_YYYY-MM-DD_Release"])
                mm_l = _dec(row.get("M_Money_Positions_Long_All"))
                mm_s = _dec(row.get("M_Money_Positions_Short_All"))
                c_l = _dec(row.get("Prod_Merc_Positions_Long_ALL"))
                c_s = _dec(row.get("Prod_Merc_Positions_Short_ALL"))
                oi = _dec(row.get("Open_Interest_All"))
            except (KeyError, ValueError, InvalidOperation):
                continue
            if start and obs < start:
                continue
            mm_n = (mm_l - mm_s) if mm_l is not None and mm_s is not None else None
            c_n = (c_l - c_s) if c_l is not None and c_s is not None else None
            out.append(
                CotRow(
                    obs_date=obs,
                    release_date=rel,
                    mm_long=mm_l,
                    mm_short=mm_s,
                    mm_net=mm_n,
                    comm_long=c_l,
                    comm_short=c_s,
                    comm_net=c_n,
                    open_interest=oi,
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
            logger.debug("cftc_cot telemetry %r", event)

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


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace(",", "").strip())
    except (InvalidOperation, ValueError):
        return None
