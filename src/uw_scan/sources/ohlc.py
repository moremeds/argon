"""OHLC provider protocol + Massive.com concrete implementation.

Provider returns typed dataclasses; persistence is the caller's responsibility.
The repository layer stores them in `daily_ohlc`. Intraday spot persistence
is now owned by ``uw_scan.worker.massive_ws_consumer`` (WebSocket pipeline);
the legacy ``fetch_intraday_quote`` REST path was removed in Phase 7.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from typing import Any, Protocol

import httpx

from uw_scan.sources._http import RequestOutcome, get_with_telemetry, request_event

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
            trust_env=False,
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
        def record(outcome: RequestOutcome) -> None:
            if self._telemetry_recorder is None:
                return
            event = request_event(
                outcome,
                provider="massive",
                endpoint_key=endpoint_key,
                path=path,
                path_template=path_template,
                params=params,
                job_name=self._job_name,
                ticker=ticker.upper(),
                provider_request_id=(
                    self._extract_request_id(outcome.response)
                    if outcome.response is not None
                    else None
                ),
            )
            try:
                self._telemetry_recorder.record(event)  # type: ignore[attr-defined]
            except Exception as exc:
                logger.exception(
                    "failed to emit Massive request telemetry for %s: %s",
                    endpoint_key,
                    repr(exc),
                )

        return get_with_telemetry(
            self._client,
            path,
            params=params,
            record=record,
            transport_error_text=lambda exc: str(exc)[:1000] or None,
            error_body_text=lambda r: (
                (r.text[:1000] or None) if r.status_code >= 400 else None
            ),
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
