"""Daily ETF holdings for the gold complex.

Targets: GLD and GLDM, both from SPDR's historical archive API (one endpoint,
``product=<ticker>``); normalised to EtfHoldingRow.

IAU (iShares) and PHYS (Sprott) were removed 2026-10: the iShares history
download needs a sign-in and Sprott's API answers 403 to non-browser clients.
Neither ever wrote a row on prod. WGC monthly files still cover both funds.
"""

from __future__ import annotations

import csv
import io
import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from openpyxl import load_workbook

from uw_scan.sources._http import (
    BROWSER_UA,
    RequestOutcome,
    get_with_telemetry,
    record_or_log,
    request_event,
)
from uw_scan.storage.provider_usage import ExternalApiRequestEvent

logger = logging.getLogger(__name__)

_RETRYABLE = (httpx.ReadTimeout, httpx.ConnectTimeout, httpx.ReadError)


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
    SPDR_ARCHIVE_URL = "https://api.spdrgoldshares.com/api/v1/historical-archive"
    PROVIDER = "etf_holdings"

    DEFAULT_TIMEOUT_S = 60.0
    MAX_RETRIES = 3

    def __init__(
        self,
        *,
        timeout_s: float | None = None,
        max_retries: int | None = None,
        record_request: RecordHook | None = None,
    ):
        self._client = httpx.Client(
            timeout=timeout_s if timeout_s is not None else self.DEFAULT_TIMEOUT_S,
            headers={"User-Agent": BROWSER_UA},
            trust_env=False,
        )
        self._max_retries = max_retries if max_retries is not None else self.MAX_RETRIES
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "EtfHoldingsProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_gld(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        return self.fetch_gld_payload(start=start)[3]

    def fetch_gld_payload(
        self, *, start: date | None = None
    ) -> tuple[bytes, str, str, list[EtfHoldingRow]]:
        """The rows AND the bytes, media type and URL they came from.

        One fetch, two consumers -- the warm store wants rows, the macro evidence store
        wants a hashable artifact. The media type is REPORTED rather than assumed because
        SPDR serves this same archive as CSV or XLSX depending on the day, and an
        artifact mislabelled ``text/csv`` is one a replay cannot re-parse.
        """
        return self._fetch_spdr_archive("GLD", start)

    def fetch_gldm(self, *, start: date | None = None) -> list[EtfHoldingRow]:
        return self._fetch_spdr_archive("GLDM", start)[3]

    def _fetch_spdr_archive(
        self, ticker: str, start: date | None
    ) -> tuple[bytes, str, str, list[EtfHoldingRow]]:
        response = self._get_with_telemetry(
            self.SPDR_ARCHIVE_URL,
            {"product": ticker.lower(), "exchange": "NYSE", "lang": "en"},
            endpoint_key=f"spdr_{ticker.lower()}_archive",
        )
        response.raise_for_status()
        source_url = str(response.request.url)
        if _looks_like_xlsx(response):
            return (
                response.content,
                "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                source_url,
                self._parse_spdr_archive_xlsx(ticker, response.content, start),
            )
        return (
            response.content,
            "text/csv",
            source_url,
            self._parse_spdr_csv(ticker, response.text, start),
        )

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

    def _parse_spdr_archive_xlsx(
        self, ticker: str, content: bytes, start: date | None
    ) -> list[EtfHoldingRow]:
        out: list[EtfHoldingRow] = []
        workbook = load_workbook(io.BytesIO(content), read_only=True, data_only=True)
        sheet_name = f"US {ticker} Historical Archive"
        sheet = workbook[sheet_name] if sheet_name in workbook.sheetnames else None
        if sheet is None:
            logger.warning("spdr archive missing sheet %s", sheet_name)
            return out

        rows = sheet.iter_rows(values_only=True)
        header = next(rows, None)
        if header is None:
            return out
        columns = {str(value).strip(): idx for idx, value in enumerate(header) if value}
        for row in rows:
            d = _parse_date(_cell(row, columns, "Date"))
            if d is None or (start and d < start):
                continue
            holdings_oz = _dec(_cell(row, columns, "Total Ounces of Gold in the Trust"))
            if holdings_oz is None:
                continue
            out.append(
                EtfHoldingRow(
                    ticker=ticker,
                    obs_date=d,
                    holdings_oz=holdings_oz,
                    shares_out=None,
                    nav_per_share=_dec(_cell(row, columns, "NAV/Share at 10:30am NYT")),
                    premium_pct=_dec(
                        _cell(
                            row,
                            columns,
                            f"Premium/Discount of {ticker} Mid Point vs Indicative "
                            f"Value of {ticker} at 4:15pm NYT",
                        )
                    ),
                )
            )
        return out

    def _get_with_telemetry(
        self, url: str, params: dict[str, Any], *, endpoint_key: str
    ) -> httpx.Response:
        def record(outcome: RequestOutcome) -> None:
            event = request_event(
                outcome,
                provider=self.PROVIDER,
                endpoint_key=endpoint_key,
                path=url,
                params=params,
            )
            record_or_log(self._record_request_fn, self, event, "etf_holdings")

        for attempt in range(self._max_retries):

            def error_text(exc: httpx.HTTPError, attempt: int = attempt) -> str:
                if isinstance(exc, _RETRYABLE):
                    return f"attempt {attempt + 1}: {repr(exc)[:900]}"
                return repr(exc)[:1000]

            try:
                return get_with_telemetry(
                    self._client,
                    url,
                    params=params,
                    record=record,
                    transport_error_text=error_text,
                )
            except _RETRYABLE:
                if attempt < self._max_retries - 1:
                    time.sleep(2**attempt)
                    continue
                raise
        raise AssertionError("max_retries must be at least 1")


def _parse_date(raw: str | None) -> date | None:
    if not raw:
        return None
    if isinstance(raw, datetime):
        return raw.date()
    if isinstance(raw, date):
        return raw
    raw = str(raw).strip()
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError as exc:
            logger.debug("etf date parse fmt=%s skipped: %s", fmt, repr(exc))
            continue
    return None


def _looks_like_xlsx(response: httpx.Response) -> bool:
    content_type = response.headers.get("content-type", "").lower()
    return (
        response.content.startswith(b"PK\x03\x04")
        or "spreadsheetml.sheet" in content_type
    )


def _cell(row: tuple[Any, ...], columns: dict[str, int], name: str) -> Any:
    idx = columns.get(name)
    if idx is None or idx >= len(row):
        return None
    return row[idx]


def _dec(raw: Any) -> Decimal | None:
    if raw is None or raw == "":
        return None
    try:
        return Decimal(str(raw).replace(",", ""))
    except (InvalidOperation, ValueError) as exc:
        logger.debug("etf decimal parse skipped: %s", repr(exc))
        return None
