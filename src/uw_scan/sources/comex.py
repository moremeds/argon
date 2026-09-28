"""COMEX gold-stocks daily scraper.

URL pattern (subject to CME publishing changes — sanity-check before deploy):
https://www.cmegroup.com/markets/metals/precious/gold-stocks.html
"""

from __future__ import annotations

import logging
import re
from collections.abc import Callable
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from typing import Any

import httpx
from bs4 import BeautifulSoup

from uw_scan.sources.http_telemetry import get_with_telemetry
from uw_scan.storage.provider_usage import ExternalApiRequestEvent

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class ComexVaultRow:
    obs_date: date
    registered_oz: Decimal | None
    eligible_oz: Decimal | None
    total_oz: Decimal | None


RecordHook = Callable[["ComexProvider", ExternalApiRequestEvent], None]


class ComexProvider:
    URL = "https://www.cmegroup.com/markets/metals/precious/gold-stocks.html"
    ENDPOINT_PATH = "/markets/metals/precious/gold-stocks.html"
    ENDPOINT_KEY = "comex_gold_stocks_html"
    PROVIDER = "comex"

    BROWSER_UA = (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 13_0) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    )

    def __init__(
        self,
        *,
        timeout_s: float = 60.0,
        record_request: RecordHook | None = None,
    ):
        self._client = httpx.Client(
            timeout=timeout_s, headers={"User-Agent": self.BROWSER_UA}
        )
        self._record_request_fn = record_request

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "ComexProvider":
        return self

    def __exit__(self, *_exc: object) -> None:
        self.close()

    def fetch_vault(self, *, start: date | None = None) -> list[ComexVaultRow]:
        response = self._get_with_telemetry(self.URL, {})
        response.raise_for_status()
        soup = BeautifulSoup(response.text, "html.parser")
        table = soup.find("table", {"id": re.compile(r"metal-stocks-gold")})
        if table is None:
            logger.warning("comex: vault table not found")
            return []
        out: list[ComexVaultRow] = []
        for tr in table.find_all("tr")[1:]:
            cells = [c.get_text(strip=True) for c in tr.find_all("td")]
            if len(cells) < 4:
                continue
            d = _parse_date(cells[0])
            if d is None or (start and d < start):
                continue
            out.append(
                ComexVaultRow(
                    obs_date=d,
                    registered_oz=_dec(cells[1]),
                    eligible_oz=_dec(cells[2]),
                    total_oz=_dec(cells[3]),
                )
            )
        return out

    def _get_with_telemetry(self, url: str, params: dict[str, Any]) -> httpx.Response:
        return get_with_telemetry(
            self._client,
            url,
            params,
            provider=self.PROVIDER,
            endpoint_key=self.ENDPOINT_KEY,
            endpoint_path=self.ENDPOINT_PATH,
            record_request=self._record_request,
        )

    def _record_request(self, event: ExternalApiRequestEvent) -> None:
        if self._record_request_fn is not None:
            self._record_request_fn(self, event)
        else:
            logger.debug("comex telemetry %r", event)


def _parse_date(raw: str) -> date | None:
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError as exc:
            logger.debug("comex date parse fmt=%s skipped: %s", fmt, repr(exc))
            continue
    return None


def _dec(raw: str) -> Decimal | None:
    if not raw:
        return None
    try:
        return Decimal(raw.replace(",", "").strip())
    except (InvalidOperation, ValueError) as exc:
        logger.debug("comex decimal parse skipped: %s", repr(exc))
        return None
