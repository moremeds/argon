"""CFTC Commitments of Traders (disaggregated) for COMEX gold futures.

Source: cftc.gov public reports / API.
We persist managed-money longs/shorts/net, commercials longs/shorts/net, OI.
"""

from __future__ import annotations

import csv
import io
import json
import logging
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

logger = logging.getLogger(__name__)

CFTC_GOLD_DISAGG_URL = (
    "https://www.cftc.gov/dea/newcot/f_disagg.txt"
)
CFTC_GOLD_DISAGG_HISTORY_URL = (
    "https://publicreporting.cftc.gov/resource/72hh-3qpy.json"
)
CFTC_GOLD_CONTRACT_MARKET_CODE = "088691"

_CURRENT_FIELD_NAMES = (
    "Market_and_Exchange_Names",
    "As_of_Date_In_Form_YYMMDD",
    "Report_Date_as_YYYY-MM-DD",
    "CFTC_Contract_Market_Code",
    "CFTC_Market_Code",
    "CFTC_Region_Code",
    "CFTC_Commodity_Code",
    "Open_Interest_All",
    "Prod_Merc_Positions_Long_All",
    "Prod_Merc_Positions_Short_All",
    "Swap_Positions_Long_All",
    "Swap__Positions_Short_All",
    "Swap__Positions_Spread_All",
    "M_Money_Positions_Long_All",
    "M_Money_Positions_Short_All",
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
    HISTORY_URL = CFTC_GOLD_DISAGG_HISTORY_URL
    ENDPOINT_PATH = "/dea/newcot/f_disagg.txt"
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
        if start is not None:
            return self._fetch_history_weekly(start=start)
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        out: list[CotRow] = []
        for row in _iter_disaggregated_rows(response.text):
            contract_code = _field(row, "CFTC_Contract_Market_Code")
            if contract_code and contract_code != CFTC_GOLD_CONTRACT_MARKET_CODE:
                continue
            try:
                cot_row = _cot_row_from_mapping(row)
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.debug("cftc cot row parse skipped: %s", repr(exc))
                continue
            out.append(cot_row)
        return out

    def _fetch_history_weekly(self, *, start: date) -> list[CotRow]:
        params = {
            "$where": (
                f'cftc_contract_market_code="{CFTC_GOLD_CONTRACT_MARKET_CODE}" '
                f'AND report_date_as_yyyy_mm_dd >= "{start.isoformat()}T00:00:00"'
            ),
            "$order": "report_date_as_yyyy_mm_dd ASC",
            "$limit": "5000",
        }
        response = self._get_with_telemetry(self.HISTORY_URL, params)
        response.raise_for_status()
        out: list[CotRow] = []
        for row in json.loads(response.text):
            contract_code = _field(row, "cftc_contract_market_code")
            if contract_code != CFTC_GOLD_CONTRACT_MARKET_CODE:
                continue
            try:
                out.append(_cot_row_from_mapping(row))
            except (KeyError, ValueError, InvalidOperation) as exc:
                logger.debug("cftc cot history row parse skipped: %s", repr(exc))
                continue
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
    except (InvalidOperation, ValueError) as exc:
        logger.debug("cftc decimal parse skipped: %s", repr(exc))
        return None


def _field(row: dict[str, Any], *names: str) -> str:
    for name in names:
        value = row.get(name)
        if value is not None and value != "":
            return str(value).strip()
    return ""


def _obs_date(row: dict[str, Any]) -> date:
    raw = _field(row, "Report_Date_as_YYYY-MM-DD", "report_date_as_yyyy_mm_dd")
    return date.fromisoformat(raw[:10])


def _cot_row_from_mapping(row: dict[str, Any]) -> CotRow:
    obs = _obs_date(row)
    rel = _release_date(row, obs)
    mm_l = _dec(_field(row, "M_Money_Positions_Long_All", "m_money_positions_long_all"))
    mm_s = _dec(_field(row, "M_Money_Positions_Short_All", "m_money_positions_short_all"))
    c_l = _dec(
        _field(
            row,
            "Prod_Merc_Positions_Long_All",
            "Prod_Merc_Positions_Long_ALL",
            "prod_merc_positions_long",
        )
    )
    c_s = _dec(
        _field(
            row,
            "Prod_Merc_Positions_Short_All",
            "Prod_Merc_Positions_Short_ALL",
            "prod_merc_positions_short",
        )
    )
    oi = _dec(_field(row, "Open_Interest_All", "open_interest_all"))
    mm_n = (mm_l - mm_s) if mm_l is not None and mm_s is not None else None
    c_n = (c_l - c_s) if c_l is not None and c_s is not None else None
    return CotRow(
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


def _iter_disaggregated_rows(text: str) -> list[dict[str, str]]:
    sample = text.lstrip()
    first_line = sample.splitlines()[0] if sample else ""
    if "Report_Date_as_YYYY-MM-DD" in first_line:
        return list(csv.DictReader(io.StringIO(text)))
    return list(csv.DictReader(io.StringIO(text), fieldnames=_CURRENT_FIELD_NAMES))


def _release_date(row: dict[str, Any], obs: date) -> date:
    raw = row.get("Report_Date_as_YYYY-MM-DD_Release")
    if raw:
        return date.fromisoformat(raw)
    return obs + timedelta(days=3)
