"""Async WebSocket client for api.massive.com.

Pure I/O — no DB writes, no buffering, no business logic. The consumer is
responsible for buffering and persistence. See worker/massive_ws_consumer.py
for the long-lived process that wires this together.

Channel grammar (Polygon-parity, verified in Phase 0 against
https://massive.com/docs/websocket/stocks/aggregates-per-second):
- A.<TICKER>  — per-second aggregate (close price `c`, epoch ms `e`)
- AM.<TICKER> — per-minute aggregate (same shape)
- T.<TICKER>  — individual trades (price `p`, epoch ms `t`)
"""

from __future__ import annotations

import asyncio
import decimal
import json
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

import websockets
from websockets.exceptions import ConnectionClosed

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class WsTick:
    ticker: str
    price: Decimal
    quoted_at: datetime
    channel: str  # "A" | "AM" | "T"


def parse_ws_message(raw: str | bytes) -> list[WsTick]:
    """Parse a WS frame (always a JSON array) into zero or more WsTicks.

    Returns [] for status / control messages. Raises ValueError on malformed
    JSON at the frame level. Per-row failures (malformed Decimal, bad epoch,
    bad shape) are caught and the row is silently skipped — one bad tick
    must NOT take down the entire frame (A4 adversarial fix).
    """
    if isinstance(raw, bytes):
        # Massive sends UTF-8 text frames; if binary arrives, decode best-effort.
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"non-utf8 binary frame: {exc!r}") from exc

    payload = json.loads(raw)
    if not isinstance(payload, list):
        return []
    ticks: list[WsTick] = []
    for row in payload:
        if not isinstance(row, dict):
            continue
        try:
            ev = row.get("ev")
            if ev not in ("A", "AM", "T"):
                continue
            sym = row.get("sym")
            if not sym:
                continue
            # Price field: "c" for aggregates, "p" for trades.
            # Epoch field: "e" for aggregates, "t" for trades.
            price_raw = row.get("c") if ev in ("A", "AM") else row.get("p")
            epoch_ms = row.get("e") if ev in ("A", "AM") else row.get("t")
            if price_raw is None or epoch_ms is None:
                continue
            ticks.append(
                WsTick(
                    ticker=str(sym).upper(),
                    price=Decimal(str(price_raw)),
                    quoted_at=datetime.fromtimestamp(
                        int(epoch_ms) / 1000, tz=timezone.utc
                    ),
                    channel=str(ev),
                )
            )
        except (ValueError, TypeError, KeyError, decimal.InvalidOperation) as exc:
            logger.debug("parse_ws_message skipping bad row %r: %s", row, repr(exc))
            continue
    return ticks


class MassiveWsClient:
    """Async context manager wrapping a websockets.connect lifecycle.

    Usage:

        async with MassiveWsClient(url, api_key) as client:
            await client.subscribe(["A.AAPL", "A.MSFT"])
            async for tick in client.ticks():
                ...

    Reconnect / backoff is the caller's responsibility — this class is a
    single connection. See `massive_ws_consumer.py` for reconnect logic.
    """

    def __init__(
        self,
        url: str,
        api_key: str,
        *,
        open_timeout: float = 10.0,
        ping_interval: float = 20.0,
    ) -> None:
        self._url = url
        self._api_key = api_key
        self._open_timeout = open_timeout
        self._ping_interval = ping_interval
        self._ws: Any = None
        self._subscribed: set[str] = set()

    async def __aenter__(self) -> MassiveWsClient:
        self._ws = await websockets.connect(
            self._url,
            open_timeout=self._open_timeout,
            ping_interval=self._ping_interval,
        )
        await self._authenticate()
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _authenticate(self) -> None:
        """Send auth and verify the broker accepts our key.

        Raises ``RuntimeError`` if the broker does not return
        ``status: "auth_success"`` within 5s. Silently accepting an auth
        failure would leave us subscribed-but-receiving-nothing — the
        no-fallback design makes this category of failure especially
        important to detect (R13).

        Massive sends a ``status: connected`` message immediately on connect
        (before auth) — we accept up to 3 status frames in the auth window
        so the initial "Connected Successfully" doesn't fool us.
        """
        assert self._ws is not None
        await self._ws.send(json.dumps({"action": "auth", "params": self._api_key}))
        auth_ok = False
        try:
            async with asyncio.timeout(5.0):
                for _ in range(3):
                    raw = await self._ws.recv()
                    logger.info("massive_ws auth response: %s", str(raw)[:200])
                    try:
                        payload = json.loads(raw)
                    except ValueError as exc:
                        raise RuntimeError(
                            f"massive_ws auth response not JSON: {str(raw)[:200]!r}"
                        ) from exc
                    items = payload if isinstance(payload, list) else [payload]
                    for m in items:
                        if not isinstance(m, dict):
                            continue
                        status = m.get("status")
                        if m.get("ev") == "status" and status == "auth_success":
                            auth_ok = True
                            break
                        if m.get("ev") == "status" and status in {
                            "auth_failed",
                            "auth_timeout",
                        }:
                            raise RuntimeError(
                                f"massive_ws auth rejected: {str(raw)[:200]!r}"
                            )
                    if auth_ok:
                        break
        except asyncio.TimeoutError as exc:
            raise RuntimeError("massive_ws auth response timed out after 5s") from exc
        if not auth_ok:
            raise RuntimeError("massive_ws auth_success not received within 3 frames")

    async def subscribe(self, channels: Iterable[str]) -> None:
        """Send a subscribe message for the given fully-qualified channels.

        Channels are strings like "A.AAPL". Idempotent — re-subscribing to an
        already-subscribed channel is a no-op (the broker dedupes).
        """
        assert self._ws is not None
        new_subs = [c for c in channels if c not in self._subscribed]
        if not new_subs:
            return
        await self._ws.send(
            json.dumps({"action": "subscribe", "params": ",".join(new_subs)})
        )
        self._subscribed.update(new_subs)

    async def unsubscribe(self, channels: Iterable[str]) -> None:
        assert self._ws is not None
        drop = [c for c in channels if c in self._subscribed]
        if not drop:
            return
        await self._ws.send(
            json.dumps({"action": "unsubscribe", "params": ",".join(drop)})
        )
        self._subscribed.difference_update(drop)

    async def ticks(self) -> AsyncIterator[WsTick]:
        """Yield ticks until the connection closes."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    for tick in parse_ws_message(raw):
                        yield tick
                except ValueError as exc:
                    logger.warning(
                        "massive_ws bad frame, skipping: %s (%s)",
                        repr(exc),
                        str(raw)[:200],
                    )
        except ConnectionClosed as exc:
            logger.info("massive_ws connection closed: %s", repr(exc))
            return
