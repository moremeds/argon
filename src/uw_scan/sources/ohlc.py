"""OHLC provider protocol + Massive.com concrete implementation.

Provider returns typed dataclasses; persistence is the caller's responsibility.
The repository layer stores them in `daily_ohlc`. Intraday spot persistence
is now owned by ``uw_scan.worker.massive_ws_consumer`` (WebSocket pipeline);
the legacy ``fetch_intraday_quote`` REST path was removed in Phase 7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import UTC, date, datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

import httpx

from uw_scan.storage.provider_usage import ExternalApiRequestEvent
from uw_scan.storage.repository import redact_params, status_family_for

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


class OhlcProvider(Protocol):
    def fetch_daily(self, ticker: str, start: date, end: date) -> list[OhlcBar]: ...


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
        telemetry_recorder: object | None = None,
        job_name: str | None = None,
    ) -> None:
        self._client = httpx.Client(
            base_url=base_url,
            headers={"Authorization": f"Bearer {api_key}"},
            timeout=timeout,
        )
        self._telemetry_recorder = telemetry_recorder
        self._job_name = job_name

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> "MassiveOhlcProvider":
        return self

    def __exit__(self, *_exc) -> None:
        self.close()

    def fetch_daily(self, ticker: str, start: date, end: date) -> list[OhlcBar]:
        return self.fetch_daily_payload(ticker, start, end)[2]

    def fetch_daily_payload(
        self, ticker: str, start: date, end: date
    ) -> tuple[bytes, str, list[OhlcBar]]:
        """The bars AND the bytes they were parsed from, plus the URL that served them.

        One fetch, two consumers: the warm store wants the bars and the macro evidence
        store wants an artifact it can hash and replay from. Fetching twice would cost a
        second vendor call and -- worse -- could return a different payload, so the
        stored artifact would not be the bytes the stored observations came from.
        """
        path = (
            f"/v2/aggs/ticker/{ticker}/range/1/day/"
            f"{start.isoformat()}/{end.isoformat()}"
        )
        r = self._get_with_telemetry(
            endpoint_key="daily_ohlc",
            path_template="/v2/aggs/ticker/{ticker}/range/1/day/{from}/{to}",
            path=path,
            ticker=ticker,
        )
        r.raise_for_status()
        raw_bytes = r.content
        source_url = str(r.request.url)
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
        return raw_bytes, source_url, bars

    def _get_with_telemetry(
        self,
        *,
        endpoint_key: str,
        path_template: str,
        path: str,
        ticker: str,
        params: dict[str, object] | None = None,
    ) -> httpx.Response:
        started_at = datetime.now(UTC)
        try:
            response = self._client.get(path, params=params)
        except httpx.HTTPError as exc:
            finished_at = datetime.now(UTC)
            self._record_request(
                endpoint_key=endpoint_key,
                path_template=path_template,
                path=path,
                ticker=ticker,
                params=params,
                status_code=None,
                started_at=started_at,
                finished_at=finished_at,
                provider_request_id=None,
                error_message=str(exc),
            )
            raise
        finished_at = datetime.now(UTC)
        provider_request_id = self._extract_request_id(response)
        self._record_request(
            endpoint_key=endpoint_key,
            path_template=path_template,
            path=path,
            ticker=ticker,
            params=params,
            status_code=response.status_code,
            started_at=started_at,
            finished_at=finished_at,
            provider_request_id=provider_request_id,
            error_message=response.text if response.status_code >= 400 else None,
        )
        return response

    def _record_request(
        self,
        *,
        endpoint_key: str,
        path_template: str,
        path: str,
        ticker: str,
        params: dict[str, object] | None,
        status_code: int | None,
        started_at: datetime,
        finished_at: datetime,
        provider_request_id: str | None,
        error_message: str | None,
    ) -> None:
        if self._telemetry_recorder is None:
            return
        event = ExternalApiRequestEvent(
            provider="massive",
            endpoint_key=endpoint_key,
            method="GET",
            path_template=path_template,
            path=path,
            ticker=ticker.upper(),
            params=redact_params(params),
            status_code=status_code,
            status_family=status_family_for(status_code),
            started_at=started_at,
            finished_at=finished_at,
            latency_ms=max(0, int((finished_at - started_at).total_seconds() * 1000)),
            job_name=self._job_name,
            provider_request_id=provider_request_id,
            error_message=error_message[:1000] if error_message else None,
        )
        try:
            self._telemetry_recorder.record(event)  # type: ignore[attr-defined]
        except Exception as exc:
            logger.exception(
                "failed to emit Massive request telemetry for %s: %s",
                endpoint_key,
                repr(exc),
            )

    def _extract_request_id(self, response: httpx.Response) -> str | None:
        try:
            payload: Any = response.json()
        except ValueError as exc:
            logger.debug("Massive response did not include JSON: %s", repr(exc))
            return None
        if isinstance(payload, dict):
            request_id = payload.get("request_id")
            if request_id is not None:
                return str(request_id)
        return None
