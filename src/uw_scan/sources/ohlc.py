"""OHLC provider protocol + Massive.com concrete implementation.

Provider returns typed dataclasses; persistence is the caller's responsibility.
The repository layer stores them in `daily_ohlc` and `intraday_quote`.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from typing import Protocol

import httpx

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class OhlcBar:
    ticker: str
    date: date
    open: Decimal | None
    high: Decimal | None
    low: Decimal | None
    close: Decimal
    volume: int | None


@dataclass(frozen=True)
class IntradayQuote:
    ticker: str
    price: Decimal
    quoted_at: datetime  # tz-aware UTC


class OhlcProvider(Protocol):
    def fetch_daily(self, ticker: str, start: date, end: date) -> list[OhlcBar]: ...
    def fetch_intraday_quote(
        self, ticker: str, *, market_date: date | None = None
    ) -> IntradayQuote | None: ...


class MassiveOhlcProvider:
    """REST client for api.massive.com (Polygon-shaped API).

    Endpoints (confirmed via spike on 2026-05-12):
    - GET /v2/aggs/ticker/{ticker}/range/1/day/{from}/{to} → daily bars
    - GET /v2/aggs/ticker/{ticker}/range/1/minute/{from}/{to}?sort=desc&limit=1
        → latest minute aggregate (15-min delayed on our tier).
        Used as a stand-in for /v3/quotes which is gated behind a paid tier.
    """

    def __init__(
        self,
        api_key: str,
        base_url: str = "https://api.massive.com",
        timeout: float = 10.0,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MassiveOhlcProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_daily(self, ticker: str, start: date, end: date) -> list[OhlcBar]:
        path = (
            f"/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        r = self._client.get(path)
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results") or []
        bars: list[OhlcBar] = []
        for row in results:
            t_ms = row.get("t")
            if t_ms is None or row.get("c") is None:
                continue
            bar_date = datetime.fromtimestamp(t_ms / 1000, tz=timezone.utc).date()
            bars.append(
                OhlcBar(
                    ticker=ticker,
                    date=bar_date,
                    open=Decimal(str(row["o"])) if row.get("o") is not None else None,
                    high=Decimal(str(row["h"])) if row.get("h") is not None else None,
                    low=Decimal(str(row["l"])) if row.get("l") is not None else None,
                    close=Decimal(str(row["c"])),
                    volume=int(row["v"]) if row.get("v") is not None else None,
                )
            )
        return bars

    def fetch_intraday_quote(
        self, ticker: str, *, market_date: date | None = None
    ) -> IntradayQuote | None:
        """Latest 15-min-delayed intraday price.

        massive.com's /v3/quotes endpoint requires a paid plan; on our tier it
        returns 403 NOT_AUTHORIZED. /v2/aggs/ticker/.../range/1/minute is open
        and returns the same data shape with status="DELAYED". Spike on
        2026-05-12 verified the substitution.
        """
        today = market_date or datetime.now(timezone.utc).date()
        tomorrow = today + timedelta(days=1)
        path = (
            f"/v2/aggs/ticker/{ticker}/range/1/minute/"
            f"{today.isoformat()}/{tomorrow.isoformat()}"
        )
        r = self._client.get(path, params={"sort": "desc", "limit": 1})
        if r.status_code == 404:
            return None
        r.raise_for_status()
        payload = r.json()
        results = payload.get("results") or []
        if not results:
            return None
        latest = results[0]
        c = latest.get("c")
        t_ms = latest.get("t")
        if c is None or t_ms is None:
            return None
        return IntradayQuote(
            ticker=ticker,
            price=Decimal(str(c)),
            quoted_at=datetime.fromtimestamp(int(t_ms) / 1000, tz=timezone.utc),
        )
