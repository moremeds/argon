"""Async WebSocket client for xenon's IB realtime server (primary live feed).

Pure I/O — no DB writes, no buffering, no business logic (same contract as
massive_ws.py). Translates xenon's protocol into the existing ``WsTick``
stream so the consumer/persistence path stays provider-agnostic:

- subscribe: one JSON object ``{action, symbols[], indexes[{symbol,
  exchange}], contracts[]}`` — stocks/ETFs go in ``symbols`` (IB SMART
  routing), index symbols (SPX/VIX/...) go in ``indexes`` with exchange CBOE.
- inbound: ``{type: status|price|batch|subscribed|unsubscribed|fundamentals|
  error}``. ``batch.updates`` is ``{SYMBOL: quote}`` flushed ~100ms;
  ``price`` is the initial snapshot. Only ``last`` + ``timestamp`` are
  consumed.

The server is the sibling xenon project's ib_realtime_server.js. It streams
24h whenever IB Gateway is connected (not just the massive 04:00-20:00 ET
window) and persists across xenon web restarts. It writes its actual port to
/tmp/xenon-ib-realtime.json (8765 may be taken) — ``discover_xenon_ws_url``
consults that file for localhost URLs only.

Failover policy lives in worker/massive_ws_consumer.py; this module only
signals ``XenonFeedUnavailable`` when the feed cannot deliver ticks at
connect time (IB Gateway down / bad handshake).
"""

from __future__ import annotations

import asyncio
import decimal
import json
import logging
from collections.abc import AsyncIterator, Iterable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit, urlunsplit

import websockets
from websockets.exceptions import ConnectionClosed

from uw_scan.sources.massive_ws import WsTick

logger = logging.getLogger(__name__)

# Index instruments need {symbol, exchange} routing on IB; everything else
# resolves via SMART as a plain symbol. Extend here when the watchlist grows
# a new index (worst case: an unknown index subscribed as a stock symbol
# fails IB resolution server-side and simply never ticks).
XENON_INDEX_SYMBOLS: frozenset[str] = frozenset(
    {
        "SPX",
        "XSP",
        "NDX",
        "XND",
        "RUT",
        "DJX",
        "VIX",
        "VVIX",
        "VIX1D",
        "VIX9D",
        "VIX3M",
        "COR1M",
    }
)
_INDEX_EXCHANGE = "CBOE"


class XenonFeedUnavailable(RuntimeError):
    """Xenon WS cannot deliver ticks (connect-time IB outage / bad handshake)."""


@dataclass(frozen=True)
class XenonFrame:
    kind: str  # "batch" | "price" | "status" | "error" | "other"
    ticks: list[WsTick] = field(default_factory=list)
    ib_connected: bool | None = None
    error: str | None = None


def _tick_from_quote(symbol: str, data: Any) -> WsTick | None:
    """One xenon quote dict -> WsTick, or None if unusable.

    Option-contract keys (TSLA_20261218_320_C) are skipped — we never
    subscribe contracts and their keys can't match watchlist tickers.
    """
    if not symbol or "_" in symbol or not isinstance(data, dict):
        return None
    last = data.get("last")
    ts_raw = data.get("timestamp")
    if last is None or not ts_raw:
        return None
    try:
        return WsTick(
            ticker=str(symbol).upper(),
            price=Decimal(str(last)),
            quoted_at=datetime.fromisoformat(str(ts_raw)).astimezone(timezone.utc),
            channel="X",
            source="xenon_ws",
        )
    except (ValueError, TypeError, decimal.InvalidOperation) as exc:
        logger.debug("xenon_ws skipping bad quote %s=%r: %s", symbol, data, repr(exc))
        return None


def parse_xenon_message(raw: str | bytes) -> XenonFrame:
    """Parse one xenon frame into a typed XenonFrame.

    Raises ValueError on frame-level malformed JSON; per-quote failures are
    silently skipped (parity with massive's A4 adversarial fix — one bad
    quote must not take down the whole batch).
    """
    if isinstance(raw, bytes):
        try:
            raw = raw.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise ValueError(f"non-utf8 binary frame: {exc!r}") from exc
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        return XenonFrame(kind="other")
    kind = str(payload.get("type") or "other")
    if kind == "batch":
        updates = payload.get("updates")
        ticks: list[WsTick] = []
        if isinstance(updates, dict):
            for symbol, data in updates.items():
                tick = _tick_from_quote(str(symbol), data)
                if tick is not None:
                    ticks.append(tick)
        return XenonFrame(kind="batch", ticks=ticks)
    if kind == "price":
        tick = _tick_from_quote(str(payload.get("symbol") or ""), payload.get("data"))
        return XenonFrame(kind="price", ticks=[tick] if tick else [])
    if kind == "status":
        ib = payload.get("ib_connected")
        return XenonFrame(
            kind="status", ib_connected=bool(ib) if ib is not None else None
        )
    if kind == "error":
        return XenonFrame(kind="error", error=str(payload.get("message") or ""))
    return XenonFrame(kind=kind)


def split_xenon_subscription(
    channels: Iterable[str],
) -> tuple[list[str], list[dict[str, str]]]:
    """Channel names ("A.SPX") -> (symbols, indexes) buckets, sorted for
    deterministic payloads. The channel prefix is a massive-ism the consumer
    loop already speaks; xenon ignores it."""
    symbols: set[str] = set()
    indexes: set[str] = set()
    for ch in channels:
        ticker = ch.split(".", 1)[-1].upper()
        (indexes if ticker in XENON_INDEX_SYMBOLS else symbols).add(ticker)
    return (
        sorted(symbols),
        [{"symbol": t, "exchange": _INDEX_EXCHANGE} for t in sorted(indexes)],
    )


def discover_xenon_ws_url(configured_url: str, port_file: str) -> str:
    """Resolve the actual xenon port from its runtime port file.

    Only applies when the configured host is local — for a remote host
    (Tailscale mini) the local port file describes a different machine.
    Any read/parse failure falls back to the configured URL.
    """
    if not port_file:
        return configured_url
    parts = urlsplit(configured_url)
    if parts.hostname not in ("localhost", "127.0.0.1", "::1"):
        return configured_url
    try:
        port = int(json.loads(Path(port_file).read_text())["port"])
    except (OSError, ValueError, KeyError, TypeError) as exc:
        logger.debug("xenon_ws port file %s unusable: %s", port_file, repr(exc))
        return configured_url
    if not (0 < port < 65536) or port == parts.port:
        return configured_url
    # Codex P2: bracket IPv6 hostnames before re-assembling the netloc.
    # ``urlsplit("ws://[::1]:8765").hostname`` returns ``::1`` (unbracketed),
    # so a naive f-string produces ``::1:9001`` which is an invalid URL.
    host = parts.hostname
    host_part = f"[{host}]" if host and ":" in host else host
    netloc = f"{host_part}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class XenonWsClient:
    """Async context manager mirroring MassiveWsClient's surface.

    Usage::

        async with XenonWsClient(url) as client:
            await client.subscribe(["A.AAPL", "A.SPX"])
            async for tick in client.ticks():
                ...

    No auth (localhost / tailnet trust). On connect, waits for the initial
    ``status`` frame: ``ib_connected: false`` raises XenonFeedUnavailable so
    the consumer fails over instead of sitting on a tickless socket.
    Mid-session IB blips are logged only — the server auto-restores IB
    subscriptions, and the consumer's quiet watchdog is the backstop.
    Reconnect/backoff is the caller's responsibility (single connection).
    """

    def __init__(
        self,
        url: str,
        *,
        open_timeout: float = 10.0,
        ping_interval: float = 20.0,
        status_timeout: float = 5.0,
    ) -> None:
        self._url = url
        self._open_timeout = open_timeout
        self._ping_interval = ping_interval
        self._status_timeout = status_timeout
        self._ws: Any = None
        self._subscribed: set[str] = set()

    async def __aenter__(self) -> XenonWsClient:
        self._ws = await websockets.connect(
            self._url,
            open_timeout=self._open_timeout,
            ping_interval=self._ping_interval,
        )
        try:
            await self._await_initial_status()
        except BaseException:
            await self._ws.close()
            self._ws = None
            raise
        return self

    async def __aexit__(self, *_exc) -> None:
        if self._ws is not None:
            await self._ws.close()
            self._ws = None

    async def _await_initial_status(self) -> None:
        """The server sends ``status`` immediately on connect. Accept up to 3
        frames in the window in case ordering ever changes server-side."""
        assert self._ws is not None
        try:
            async with asyncio.timeout(self._status_timeout):
                for _ in range(3):
                    frame = parse_xenon_message(await self._ws.recv())
                    if frame.kind != "status":
                        continue
                    if frame.ib_connected is False:
                        raise XenonFeedUnavailable(
                            "xenon connected but IB Gateway is down "
                            "(ib_connected=false)"
                        )
                    return
        except (asyncio.TimeoutError, ConnectionClosed) as exc:
            raise XenonFeedUnavailable(f"no status frame from xenon: {exc!r}") from exc
        except ValueError as exc:
            raise XenonFeedUnavailable(f"malformed handshake frame: {exc!r}") from exc
        raise XenonFeedUnavailable("no status frame within first 3 frames")

    async def _send_action(self, action: str, channels: list[str]) -> None:
        assert self._ws is not None
        symbols, indexes = split_xenon_subscription(channels)
        await self._ws.send(
            json.dumps(
                {
                    "action": action,
                    "symbols": symbols,
                    "indexes": indexes,
                    "contracts": [],
                }
            )
        )

    async def subscribe(self, channels: Iterable[str]) -> None:
        """Subscribe to fully-qualified channels ("A.AAPL"). Idempotent."""
        new = [c for c in channels if c not in self._subscribed]
        if not new:
            return
        await self._send_action("subscribe", new)
        self._subscribed.update(new)

    async def unsubscribe(self, channels: Iterable[str]) -> None:
        drop = [c for c in channels if c in self._subscribed]
        if not drop:
            return
        await self._send_action("unsubscribe", drop)
        self._subscribed.difference_update(drop)

    async def ticks(self) -> AsyncIterator[WsTick]:
        """Yield ticks until the connection closes."""
        assert self._ws is not None
        try:
            async for raw in self._ws:
                try:
                    frame = parse_xenon_message(raw)
                except ValueError as exc:
                    logger.warning(
                        "xenon_ws bad frame, skipping: %s (%s)",
                        repr(exc),
                        str(raw)[:200],
                    )
                    continue
                if frame.kind == "status" and frame.ib_connected is False:
                    logger.warning(
                        "xenon_ws: IB Gateway disconnected mid-session; awaiting "
                        "auto-restore (quiet watchdog is the failover backstop)"
                    )
                elif frame.kind == "error":
                    logger.warning("xenon_ws server error: %s", frame.error)
                for tick in frame.ticks:
                    yield tick
        except ConnectionClosed as exc:
            logger.info("xenon_ws connection closed: %s", repr(exc))
            return
