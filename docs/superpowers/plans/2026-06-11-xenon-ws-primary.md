# Xenon WS Primary / Massive Fallback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The spot WS consumer subscribes to xenon's IB realtime WebSocket (`ws://localhost:8765`) as the primary live market-data feed, falling back to massive.com's WS automatically when xenon is unavailable, and switching back when xenon recovers.

**Architecture:** A new `XenonWsClient` in `sources/xenon_ws.py` presents the exact same surface as `MassiveWsClient` (`async with` + `subscribe("A.TSLA"-style channels)` + `ticks() -> AsyncIterator[WsTick]`), translating xenon's JSON protocol (subscribe with `symbols`/`indexes` buckets, `batch`/`price` inbound frames) into the existing `WsTick` stream. `run_consumer_once` gains client injection + a market-session-aware quiet watchdog; `run_consumer_forever` gains per-session provider selection (xenon first, massive fallback for `XENON_WS_RETRY_PRIMARY_SECONDS`, timed re-probe racing the fallback session). Persistence path (`TickBuffer` → `WsDbWriter`) is untouched except the injected `source_tag` (`"xenon_ws"` vs `"massive.com_ws"`), so `watchlist_card.spot_source` and `intraday_quote.source` tell ops which feed wrote each row. A new `ws_consumer_state.active_source` column surfaces the live feed in `/api/health`.

**Tech Stack:** Python 3.13 (`uv`), `websockets`, psycopg 3, pytest (+ `websockets.serve` fake servers), FastAPI OpenAPI snapshot, `openapi-typescript`.

**Failure→failover matrix (the spec, condensed):**

| Event | Detection | Action |
|---|---|---|
| xenon port closed / host down | connect raises `OSError`/timeout | massive session immediately; block xenon for `XENON_WS_RETRY_PRIMARY_SECONDS` (default 300) |
| xenon up but IB Gateway down at connect | first `status` frame has `ib_connected: false` | raise `XenonFeedUnavailable` → same as above |
| xenon connected but feed goes silent | no raw frames for `XENON_WS_QUIET_FAILOVER_SECONDS` (default 120) **while market session active and subscriptions exist** | `_FeedQuiet` unwinds session → same as above |
| IB blips mid-session (`status` with `ib_connected:false` pushed mid-stream) | logged WARNING only | xenon auto-restores; quiet watchdog is the backstop |
| on massive fallback, xenon recovers | re-probe task (connect + status ok) every `XENON_WS_RETRY_PRIMARY_SECONDS` | cancel massive session (buffer survives — shared `TickBuffer`), next session is xenon |
| xenon enabled, massive disabled/keyless, xenon down | nothing else to run | sleep backoff, retry xenon (no dead-exit) |

**24h feed note:** xenon streams whenever IB Gateway is connected — including overnight, outside massive's Mon–Fri 04:00–20:00 ET window. The persistence path is not session-gated, so xenon-as-primary keeps `watchlist_card.spot` fresh around the clock with zero extra code. The quiet watchdog is deliberately armed ONLY inside the massive feed window: (a) failing over to massive outside that window buys nothing (massive delivers no frames then), and (b) overnight tick silence on thin names is legitimate, not a failure. If xenon's connection actually drops overnight, the normal reconnect loop (connection-close → next session tries xenon first) still covers it.

**Out of scope (YAGNI):** option-contract (`contracts`) subscriptions, xenon `fundamentals` frames (massive REST keeps that job), index symbols on massive (unchanged), web HealthPanel UI changes (API field only), renaming the `massive_ws_consumer` module (launchd plists + dev.sh reference it; it stays the spot-WS entrypoint).

**Repo policy reminders:** NO commits until the user explicitly asks (draft-first). All test runs via `uv run pytest`. Migration must be idempotent.

---

### Task 1: Config — xenon settings + `ws_spot_enabled`

**Files:**
- Modify: `src/uw_scan/config.py` (massive block ~lines 143–157; `from_env` ~lines 326–354)
- Test: `tests/unit/test_config_xenon.py` (new)

- [ ] **Step 1: Write the failing test**

```python
"""Xenon WS settings + ws_spot_enabled derivation."""

from uw_scan.config import Settings


def test_xenon_defaults() -> None:
    s = Settings()
    assert s.xenon_ws_enabled is False
    assert s.xenon_ws_url == "ws://127.0.0.1:8765"
    assert s.xenon_ws_port_file == "/tmp/xenon-ib-realtime.json"
    assert s.xenon_ws_retry_primary_seconds == 300.0
    assert s.xenon_ws_quiet_failover_seconds == 120.0


def test_xenon_env_overrides(monkeypatch) -> None:
    monkeypatch.setenv("XENON_WS_ENABLED", "true")
    monkeypatch.setenv("XENON_WS_URL", "ws://100.66.147.98:8765")
    monkeypatch.setenv("XENON_WS_PORT_FILE", "")
    monkeypatch.setenv("XENON_WS_RETRY_PRIMARY_SECONDS", "60")
    monkeypatch.setenv("XENON_WS_QUIET_FAILOVER_SECONDS", "30")
    s = Settings.from_env()
    assert s.xenon_ws_enabled is True
    assert s.xenon_ws_url == "ws://100.66.147.98:8765"
    assert s.xenon_ws_port_file == ""
    assert s.xenon_ws_retry_primary_seconds == 60.0
    assert s.xenon_ws_quiet_failover_seconds == 30.0


def test_ws_spot_enabled_is_or_of_feeds() -> None:
    assert Settings(massive_ws_enabled=False, xenon_ws_enabled=False).ws_spot_enabled is False
    assert Settings(massive_ws_enabled=True, xenon_ws_enabled=False).ws_spot_enabled is True
    assert Settings(massive_ws_enabled=False, xenon_ws_enabled=True).ws_spot_enabled is True
```

Note: mirror the existing `Settings.from_env` test conventions — if other config tests monkeypatch a clean env or pass an explicit `env_path`, copy that pattern so `.env.local` on the dev machine can't leak into the test.

- [ ] **Step 2: Run it, confirm failure** — `uv run pytest tests/unit/test_config_xenon.py -v` → AttributeError (`xenon_ws_enabled`).

- [ ] **Step 3: Implement.** In the settings class, directly under the massive WS block:

```python
# xenon IB realtime WS (primary live feed when enabled; massive WS becomes
# the fallback). Served by the sibling xenon project's ib_realtime_server.js.
# Port may drift if 8765 is taken — the server writes the actual port to
# xenon_ws_port_file; discovery only applies when the URL host is localhost.
xenon_ws_enabled: bool = False
xenon_ws_url: str = "ws://127.0.0.1:8765"
xenon_ws_port_file: str = "/tmp/xenon-ib-realtime.json"
xenon_ws_retry_primary_seconds: float = 300.0
xenon_ws_quiet_failover_seconds: float = 120.0  # 0 disables the quiet watchdog

@property
def ws_spot_enabled(self) -> bool:
    """True when ANY WS feed owns intraday spot (preserve_spot guard etc.)."""
    return self.massive_ws_enabled or self.xenon_ws_enabled
```

(If `Settings` is a plain dataclass rather than a pydantic model, the property form still works; match the file's existing style.)

In `from_env`, next to the massive WS keys:

```python
xenon_ws_enabled=os.environ.get("XENON_WS_ENABLED", "false").lower() == "true",
xenon_ws_url=os.environ.get("XENON_WS_URL", "ws://127.0.0.1:8765"),
xenon_ws_port_file=os.environ.get("XENON_WS_PORT_FILE", "/tmp/xenon-ib-realtime.json"),
xenon_ws_retry_primary_seconds=float(
    os.environ.get("XENON_WS_RETRY_PRIMARY_SECONDS", "300")
),
xenon_ws_quiet_failover_seconds=float(
    os.environ.get("XENON_WS_QUIET_FAILOVER_SECONDS", "120")
),
```

- [ ] **Step 4: Swap the two `preserve_spot=settings.massive_ws_enabled` sites** at `src/uw_scan/worker/scheduler.py:316` and `:371` to `preserve_spot=settings.ws_spot_enabled` (update the adjacent comment to say "any WS feed").

- [ ] **Step 5: Run** `uv run pytest tests/unit/test_config_xenon.py tests/unit/worker/test_scheduler.py -v` → PASS.

---

### Task 2: `sources/xenon_ws.py` — parser, URL discovery, client

**Files:**
- Create: `src/uw_scan/sources/xenon_ws.py`
- Test: `tests/unit/sources/test_xenon_ws.py` (new)

- [ ] **Step 1: Write the failing tests**

```python
"""Unit tests for the xenon IB realtime WS client (parser + lifecycle)."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
import websockets

from uw_scan.sources.xenon_ws import (
    XENON_INDEX_SYMBOLS,
    XenonFeedUnavailable,
    XenonWsClient,
    discover_xenon_ws_url,
    parse_xenon_message,
    split_xenon_subscription,
)

BATCH = json.dumps(
    {
        "type": "batch",
        "updates": {
            "SPX": {"symbol": "SPX", "last": 7293.21, "timestamp": "2026-06-11T14:31:43.838Z"},
            "HYG": {"symbol": "HYG", "last": 79.55, "timestamp": "2026-06-11T14:31:43.901Z"},
            "TSLA_20261218_320_C": {"symbol": "TSLA_20261218_320_C", "last": 12.5,
                                    "timestamp": "2026-06-11T14:31:43.9Z"},
            "QUIET": {"symbol": "QUIET", "last": None, "timestamp": "2026-06-11T14:31:43.9Z"},
        },
    }
)


def test_parse_batch_yields_ticks_skips_contracts_and_nulls() -> None:
    frame = parse_xenon_message(BATCH)
    assert frame.kind == "batch"
    by_ticker = {t.ticker: t for t in frame.ticks}
    assert set(by_ticker) == {"SPX", "HYG"}  # contract + null-last skipped
    spx = by_ticker["SPX"]
    assert spx.price == Decimal("7293.21")
    assert spx.quoted_at.isoformat() == "2026-06-11T14:31:43.838000+00:00"
    assert spx.channel == "X"


def test_parse_price_snapshot_yields_single_tick() -> None:
    raw = json.dumps(
        {"type": "price", "symbol": "AAPL",
         "data": {"symbol": "AAPL", "last": 245.5, "timestamp": "2026-06-11T14:31:43.838Z"}}
    )
    frame = parse_xenon_message(raw)
    assert frame.kind == "price"
    assert len(frame.ticks) == 1 and frame.ticks[0].ticker == "AAPL"


def test_parse_price_snapshot_with_null_last_yields_no_tick() -> None:
    raw = json.dumps({"type": "price", "symbol": "AAPL", "data": {"last": None}})
    assert parse_xenon_message(raw).ticks == []


def test_parse_status_and_error_frames() -> None:
    st = parse_xenon_message(json.dumps({"type": "status", "ib_connected": False}))
    assert st.kind == "status" and st.ib_connected is False and st.ticks == []
    err = parse_xenon_message(json.dumps({"type": "error", "message": "IB not connected"}))
    assert err.kind == "error" and err.error == "IB not connected"


def test_parse_bad_row_does_not_kill_frame() -> None:
    raw = json.dumps(
        {"type": "batch", "updates": {
            "BAD": {"last": "not-a-number", "timestamp": "2026-06-11T14:31:43.9Z"},
            "OK": {"last": 1.5, "timestamp": "2026-06-11T14:31:43.9Z"},
        }}
    )
    frame = parse_xenon_message(raw)
    assert [t.ticker for t in frame.ticks] == ["OK"]


def test_parse_malformed_json_raises() -> None:
    with pytest.raises(ValueError):
        parse_xenon_message("{not json")


def test_split_subscription_classifies_indexes() -> None:
    symbols, indexes = split_xenon_subscription(["A.SPY", "A.SPX", "A.VIX", "A.HYG"])
    assert symbols == ["HYG", "SPY"]
    assert indexes == [
        {"symbol": "SPX", "exchange": "CBOE"},
        {"symbol": "VIX", "exchange": "CBOE"},
    ]
    assert "COR1M" in XENON_INDEX_SYMBOLS


def test_discover_url_prefers_port_file_for_localhost(tmp_path) -> None:
    pf = tmp_path / "xenon.json"
    pf.write_text(json.dumps({"port": 9001, "pid": 1}))
    assert discover_xenon_ws_url("ws://127.0.0.1:8765", str(pf)) == "ws://127.0.0.1:9001"
    # non-localhost host: port file is some OTHER machine's state — ignore
    assert (
        discover_xenon_ws_url("ws://100.66.147.98:8765", str(pf))
        == "ws://100.66.147.98:8765"
    )
    # missing / malformed / disabled
    assert discover_xenon_ws_url("ws://127.0.0.1:8765", str(tmp_path / "nope.json")) == "ws://127.0.0.1:8765"
    (tmp_path / "bad.json").write_text("{")
    assert discover_xenon_ws_url("ws://127.0.0.1:8765", str(tmp_path / "bad.json")) == "ws://127.0.0.1:8765"
    assert discover_xenon_ws_url("ws://127.0.0.1:8765", "") == "ws://127.0.0.1:8765"


def _status(ib: bool = True) -> str:
    return json.dumps({"type": "status", "ib_connected": ib, "subscriptions": []})


@pytest.mark.asyncio
async def test_client_connects_subscribes_and_yields_ticks() -> None:
    received: list[dict] = []

    async def handler(ws):
        await ws.send(_status(True))
        async for msg in ws:
            received.append(json.loads(msg))
            await ws.send(json.dumps({"type": "subscribed", "symbols": ["HYG", "SPX"]}))
            await ws.send(BATCH)
            await asyncio.sleep(0.1)
            await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with XenonWsClient(f"ws://127.0.0.1:{port}") as client:
            await client.subscribe(["A.HYG", "A.SPX"])
            ticks = [t async for t in client.ticks()]

    assert received[0]["action"] == "subscribe"
    assert received[0]["symbols"] == ["HYG"]
    assert received[0]["indexes"] == [{"symbol": "SPX", "exchange": "CBOE"}]
    assert received[0]["contracts"] == []
    assert {t.ticker for t in ticks} == {"SPX", "HYG"}


@pytest.mark.asyncio
async def test_client_raises_when_ib_disconnected_at_connect() -> None:
    async def handler(ws):
        await ws.send(_status(False))
        await asyncio.sleep(1)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(XenonFeedUnavailable):
            async with XenonWsClient(f"ws://127.0.0.1:{port}"):
                pass


@pytest.mark.asyncio
async def test_client_subscribe_is_idempotent_and_unsubscribe_diffs() -> None:
    received: list[dict] = []

    async def handler(ws):
        await ws.send(_status(True))
        async for msg in ws:
            received.append(json.loads(msg))

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        async with XenonWsClient(f"ws://127.0.0.1:{port}") as client:
            await client.subscribe(["A.HYG"])
            await client.subscribe(["A.HYG"])  # no-op
            await client.unsubscribe(["A.HYG", "A.SPY"])  # only HYG sent
            await asyncio.sleep(0.1)

    assert len(received) == 2
    assert received[1]["action"] == "unsubscribe"
    assert received[1]["symbols"] == ["HYG"]
```

- [ ] **Step 2: Run** `uv run pytest tests/unit/sources/test_xenon_ws.py -v` → FAIL (module missing).

- [ ] **Step 3: Implement `src/uw_scan/sources/xenon_ws.py`**

```python
"""Async WebSocket client for xenon's IB realtime server (primary live feed).

Pure I/O — no DB writes, no buffering, no business logic (same contract as
massive_ws.py). Translates xenon's protocol into the existing ``WsTick``
stream so the consumer/persistence path is provider-agnostic:

- subscribe: one JSON object {action, symbols[], indexes[{symbol,exchange}],
  contracts[]} — stocks/ETFs go in ``symbols`` (IB SMART routing), index
  symbols (SPX/VIX/...) go in ``indexes`` with exchange CBOE.
- inbound: {type: status|price|batch|subscribed|unsubscribed|fundamentals|error}.
  ``batch.updates`` is {SYMBOL: quote} flushed ~100ms; ``price`` is the
  initial snapshot. Only ``last`` + ``timestamp`` are consumed.

The server is the sibling xenon project's ib_realtime_server.js. It writes
its actual port to /tmp/xenon-ib-realtime.json (8765 may be taken) —
``discover_xenon_ws_url`` consults that file for localhost URLs only.

Failover policy lives in worker/massive_ws_consumer.py; this module only
signals ``XenonFeedUnavailable`` when the feed cannot deliver ticks at
connect time (IB Gateway down).
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
    {"SPX", "XSP", "NDX", "XND", "RUT", "DJX",
     "VIX", "VVIX", "VIX1D", "VIX9D", "VIX3M", "COR1M"}
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
        )
    except (ValueError, TypeError, decimal.InvalidOperation) as exc:
        logger.debug("xenon_ws skipping bad quote %s=%r: %s", symbol, data, repr(exc))
        return None


def parse_xenon_message(raw: str | bytes) -> XenonFrame:
    """Parse one xenon frame. Raises ValueError on frame-level malformed JSON;
    per-quote failures are skipped (parity with massive A4 behavior)."""
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
        return XenonFrame(kind="status", ib_connected=bool(ib) if ib is not None else None)
    if kind == "error":
        return XenonFrame(kind="error", error=str(payload.get("message") or ""))
    return XenonFrame(kind=kind)


def split_xenon_subscription(channels: Iterable[str]) -> tuple[list[str], list[dict[str, str]]]:
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
    netloc = f"{parts.hostname}:{port}"
    return urlunsplit((parts.scheme, netloc, parts.path, parts.query, parts.fragment))


class XenonWsClient:
    """Async context manager mirroring MassiveWsClient's surface.

    No auth (localhost / tailnet trust). On connect, waits for the initial
    ``status`` frame: ``ib_connected: false`` raises XenonFeedUnavailable so
    the consumer fails over instead of sitting on a tickless socket.
    Mid-session IB blips are logged only — the server auto-restores
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
        frames in the window in case ordering ever changes."""
        assert self._ws is not None
        try:
            async with asyncio.timeout(self._status_timeout):
                for _ in range(3):
                    frame = parse_xenon_message(await self._ws.recv())
                    if frame.kind != "status":
                        continue
                    if frame.ib_connected is False:
                        raise XenonFeedUnavailable(
                            "xenon connected but IB Gateway is down (ib_connected=false)"
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
                {"action": action, "symbols": symbols, "indexes": indexes, "contracts": []}
            )
        )

    async def subscribe(self, channels: Iterable[str]) -> None:
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
                        "xenon_ws bad frame, skipping: %s (%s)", repr(exc), str(raw)[:200]
                    )
                    continue
                if frame.kind == "status" and frame.ib_connected is False:
                    logger.warning(
                        "xenon_ws: IB Gateway disconnected mid-session; "
                        "awaiting auto-restore (quiet watchdog is the backstop)"
                    )
                elif frame.kind == "error":
                    logger.warning("xenon_ws server error: %s", frame.error)
                for tick in frame.ticks:
                    yield tick
        except ConnectionClosed as exc:
            logger.info("xenon_ws connection closed: %s", repr(exc))
            return
```

- [ ] **Step 4: Run** `uv run pytest tests/unit/sources/test_xenon_ws.py -v` → PASS. Also `uv run pytest tests/unit/sources/test_massive_ws.py -v` (untouched, must stay green).

---

### Task 3: Consumer — client injection, source tag, quiet watchdog

**Files:**
- Modify: `src/uw_scan/worker/massive_ws_consumer.py` (`run_consumer_once`; `_ws_reader`; new `_FeedQuiet` + `_quiet_watchdog`)
- Test: `tests/integration/worker/test_xenon_ws_consumer.py` (new)

- [ ] **Step 1: Write the failing tests** (uses the same `seeded_db_with_cards` fixture as `test_massive_ws_consumer.py` — check that conftest for exact fixture import/registration):

```python
"""Integration: run_consumer_once with an injected XenonWsClient + quiet watchdog."""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
import websockets

from uw_scan.sources.xenon_ws import XenonWsClient
from uw_scan.worker.massive_ws_consumer import _FeedQuiet, run_consumer_once

STATUS_OK = json.dumps({"type": "status", "ib_connected": True, "subscriptions": []})


def _batch(prices: dict[str, float]) -> str:
    return json.dumps(
        {"type": "batch", "updates": {
            sym: {"symbol": sym, "last": px, "timestamp": "2026-06-11T14:31:43.838Z"}
            for sym, px in prices.items()
        }}
    )


@pytest.mark.asyncio
async def test_xenon_session_persists_ticks_with_xenon_source(seeded_db_with_cards):
    received: list[dict] = []

    async def handler(ws):
        await ws.send(STATUS_OK)
        async for msg in ws:
            received.append(json.loads(msg))
            await ws.send(_batch({"TSLA": 189.42, "AAPL": 425.10}))
            await asyncio.sleep(0.3)
            await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True
        await run_consumer_once(
            ws_url=url,
            api_key="",
            channel="A",
            tickers={"TSLA", "AAPL"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.1,
            run_for_seconds=1.0,
            client=XenonWsClient(url),
            source_tag="xenon_ws",
        )

    assert received[0]["action"] == "subscribe"
    assert sorted(received[0]["symbols"]) == ["AAPL", "TSLA"]
    q = repo.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("189.42")
    # source tag flows to watchlist_card.spot_source via WsDbWriter
    card = repo.get_watchlist_card("TSLA")
    assert card.spot_source == "xenon_ws"


@pytest.mark.asyncio
async def test_quiet_watchdog_raises_feed_quiet(seeded_db_with_cards, monkeypatch):
    """Server connects + acks but never sends a tick; watchdog must unwind
    the session with _FeedQuiet (in-session forced via monkeypatch)."""
    import uw_scan.worker.massive_ws_consumer as consumer_mod

    monkeypatch.setattr(
        consumer_mod, "current_market_date", lambda now, tz: now.date()
    )

    async def handler(ws):
        await ws.send(STATUS_OK)
        async for _ in ws:
            pass  # ack nothing, send no ticks

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True
        with pytest.raises(BaseExceptionGroup) as excinfo:
            await run_consumer_once(
                ws_url=url,
                api_key="",
                channel="A",
                tickers={"TSLA"},
                writer_repo=repo,
                reader_repo=repo,
                flush_interval_seconds=0.1,
                run_for_seconds=10.0,
                client=XenonWsClient(url),
                source_tag="xenon_ws",
                quiet_failover_seconds=0.5,
            )
        assert excinfo.group_contains(_FeedQuiet)
```

(If `repo.get_watchlist_card` doesn't exist under that name, use whatever accessor `test_massive_ws_consumer.py` / the watchlist storage module exposes for reading a card row — assert on `spot_source`.)

- [ ] **Step 2: Run** → FAIL (`run_consumer_once` has no `client`/`source_tag`/`quiet_failover_seconds` params; `_FeedQuiet` missing).

- [ ] **Step 3: Implement consumer changes.**

3a. Imports + module docstring tweak (now "Long-lived spot WebSocket consumer (xenon primary / massive fallback)"):

```python
import time

from uw_scan.sources.massive_ws import MassiveWsClient
from uw_scan.sources.xenon_ws import (
    XenonFeedUnavailable,
    XenonWsClient,
    discover_xenon_ws_url,
)
from uw_scan.worker.market_session import current_market_date
```

3b. New sentinel + watchdog (near `_ReaderDone`):

```python
class _FeedQuiet(Exception):
    """Sentinel: the active feed delivered no frames for quiet_failover_seconds
    during a market session while subscriptions exist. Unwinds the TaskGroup;
    run_consumer_forever treats it as a primary-feed failure (xenon sessions)
    or a plain reconnect (massive sessions)."""


async def _quiet_watchdog(
    *,
    last_rx_monotonic: list[float],
    current_subs: set[str],
    quiet_seconds: float,
    rth_tz: str,
) -> None:
    """Raise _FeedQuiet on sustained in-session silence.

    Outside the feed-active window (or with nothing subscribed) the timer is
    re-armed rather than evaluated — a session opening at 03:00 ET must not
    insta-trip at 09:30.
    """
    while True:
        await asyncio.sleep(max(min(quiet_seconds / 4.0, 15.0), 0.05))
        if current_market_date(datetime.now(timezone.utc), rth_tz) is None or not current_subs:
            last_rx_monotonic[0] = time.monotonic()
            continue
        if time.monotonic() - last_rx_monotonic[0] >= quiet_seconds:
            raise _FeedQuiet(
                f"no WS frames for {quiet_seconds:.0f}s during market session"
            )
```

3c. `_ws_reader` gains the last-rx holder (type hint widens to `MassiveWsClient | XenonWsClient`):

```python
async def _ws_reader(
    client: MassiveWsClient | XenonWsClient,
    buffer: TickBuffer,
    writer: WsDbWriter,
    last_rx_monotonic: list[float],
) -> None:
    async for tick in client.ticks():
        last_rx_monotonic[0] = time.monotonic()
        writer.note_received(1)  # A12: raw feed pressure
        buffer.add(tick)
    raise _ReaderDone("ws connection closed cleanly")
```

(Note: `last_rx` only advances on *parsed ticks*, not raw frames — for the quiet watchdog that's the correct signal anyway: a feed sending only heartbeats is still not delivering prices. Keep `_subscription_loop`'s client type hint as `MassiveWsClient | XenonWsClient` too.)

3d. `run_consumer_once` — new keyword params, client injection, source tag, watchdog task:

```python
async def run_consumer_once(
    *,
    ws_url: str,
    api_key: str,
    channel: str,
    tickers: set[str],
    writer_repo: Repository,
    reader_repo: Repository,
    flush_interval_seconds: float = 1.0,
    subscription_poll_interval_seconds: float = 30.0,
    run_for_seconds: float | None = None,
    buffer: TickBuffer | None = None,
    final_flush_timeout_seconds: float = 5.0,
    client: MassiveWsClient | XenonWsClient | None = None,
    source_tag: str = "massive.com_ws",
    quiet_failover_seconds: float = 0.0,
    rth_tz: str = "America/New_York",
) -> bool:
```

Inside (docstring gains a paragraph about `client`/`source_tag`/`quiet_failover_seconds`; existing behavior unchanged when they're left default):

```python
    if buffer is None:
        buffer = TickBuffer()
    writer = WsDbWriter(repo=writer_repo, buffer=buffer, source_tag=source_tag)
    current_subs: set[str] = set()
    last_rx_monotonic = [time.monotonic()]
    final_flush_ok = False
    if client is None:
        client = MassiveWsClient(ws_url, api_key)

    async with client:
        await asyncio.to_thread(
            writer_repo.record_ws_connection_started,
            datetime.now(timezone.utc),
            source_tag,
        )
        ...
                async with asyncio.TaskGroup() as tg:
                    tg.create_task(
                        _ws_reader(client, buffer, writer, last_rx_monotonic),
                        name="ws_reader",
                    )
                    tg.create_task(
                        _flush_loop(writer, flush_interval_seconds), name="ws_flusher"
                    )
                    tg.create_task(
                        _subscription_loop(...unchanged...), name="ws_subscriber"
                    )
                    if quiet_failover_seconds > 0:
                        tg.create_task(
                            _quiet_watchdog(
                                last_rx_monotonic=last_rx_monotonic,
                                current_subs=current_subs,
                                quiet_seconds=quiet_failover_seconds,
                                rth_tz=rth_tz,
                            ),
                            name="ws_quiet_watchdog",
                        )
```

`_FeedQuiet` is deliberately NOT caught by the `except*` clauses — it propagates (wrapped in `BaseExceptionGroup`) after the `finally` final-flush runs, so no ticks are lost on a quiet failover.

`record_ws_connection_started` gains the `source` arg in Task 4 — implement Tasks 3+4 together before running this test file, or temporarily keep the one-arg call; the plan orders the storage change next.

- [ ] **Step 4: Run** `uv run pytest tests/integration/worker/test_xenon_ws_consumer.py tests/integration/worker/test_massive_ws_consumer.py -v` → PASS (after Task 4's storage change lands).

---

### Task 4: Storage + migration + health — `active_source`

**Files:**
- Create: `src/uw_scan/storage/migrations/068_ws_active_source.sql`
- Modify: `src/uw_scan/storage/ws_consumer_state.py` (`record_ws_connection_started`, `get_ws_consumer_state`)
- Modify: `src/uw_scan/storage/rows.py:55-63` (`WsConsumerStateRow`)
- Modify: `src/uw_scan/api/routers/health.py` (`WsConsumerHealth` + populate)
- Modify: `tests/integration/api/openapi.snapshot.json` (regen)
- Modify: `web/lib/types.ts` (regen)

- [ ] **Step 1: Migration** `068_ws_active_source.sql`:

```sql
-- 068_ws_active_source.sql
-- Track which WS feed (xenon_ws | massive.com_ws) the consumer is currently
-- connected to, so /api/health can show primary-vs-fallback state.
SET search_path TO uw_scan, public;

ALTER TABLE ws_consumer_state
  ADD COLUMN IF NOT EXISTS active_source TEXT;
```

- [ ] **Step 2: Failing test** — extend `tests/integration/worker/test_xenon_ws_consumer.py::test_xenon_session_persists_ticks_with_xenon_source` with:

```python
    state = repo.get_ws_consumer_state()
    assert state.active_source == "xenon_ws"
```

Run → FAIL (no such attribute).

- [ ] **Step 3: Storage changes.** `rows.py` — append field (keep order matching SELECT):

```python
@dataclass(frozen=True)
class WsConsumerStateRow:
    last_tick_at: datetime | None
    last_flush_at: datetime | None
    ticks_received: int
    ticks_flushed: int
    connection_started_at: datetime | None
    last_error: str | None
    last_error_at: datetime | None
    updated_at: datetime
    active_source: str | None = None
```

`ws_consumer_state.py` — SELECT gains `active_source` (append to column list), and:

```python
    def record_ws_connection_started(
        self, started_at: datetime, source: str = "massive.com_ws"
    ) -> None:
        """Does NOT commit — caller controls."""
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                UPDATE {self._schema}.ws_consumer_state
                SET connection_started_at = %s, active_source = %s, updated_at = NOW()
                WHERE id = 1
                """,
                (started_at, source),
            )
```

- [ ] **Step 4: Health surfacing.** `health.py` `WsConsumerHealth` gains:

```python
    active_source: str | None = None  # "xenon_ws" | "massive.com_ws"
```

and the populated branch adds `active_source=ws_state.active_source,`.

- [ ] **Step 5: Regenerate OpenAPI snapshot + web types.** Check how `tests/integration/api/test_openapi_snapshot.py` regenerates (look for an `--update`/env-var path or a `scripts/` helper); follow that exact mechanism. Then regenerate web types from the API schema per `web/package.json` `gen:types` (needs the API serving `openapi.json` on 8400 — or dump `app.openapi()` to a temp JSON file and point `openapi-typescript` at it, same output).

- [ ] **Step 6: Run** `uv run pytest tests/integration/worker/test_xenon_ws_consumer.py tests/integration/api/test_openapi_snapshot.py -v` → PASS.

---

### Task 5: Provider selection + re-probe in `run_consumer_forever` + `main()` gating

**Files:**
- Modify: `src/uw_scan/worker/massive_ws_consumer.py` (`run_consumer_forever`, `main`; new `_xenon_probe_loop`)
- Test: `tests/integration/worker/test_xenon_failover.py` (new)

- [ ] **Step 1: Failing tests**

```python
"""Failover semantics: xenon down -> massive; xenon recovery -> switch back."""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import contextmanager
from decimal import Decimal

import pytest
import websockets

from uw_scan.config import Settings
from uw_scan.worker.massive_ws_consumer import run_consumer_forever

STATUS_OK = json.dumps({"type": "status", "ib_connected": True, "subscriptions": []})


def _xenon_batch(prices: dict[str, float]) -> str:
    return json.dumps(
        {"type": "batch", "updates": {
            sym: {"symbol": sym, "last": px, "timestamp": "2026-06-11T14:31:43.838Z"}
            for sym, px in prices.items()
        }}
    )


def _settings(base: Settings, **over) -> Settings:
    # Settings is a frozen-ish config object; build via replace/copy following
    # how test_massive_ws_consumer.py constructs per-test Settings.
    return base.model_copy(update=over) if hasattr(base, "model_copy") else ...


@pytest.mark.asyncio
async def test_xenon_down_falls_back_to_massive(seeded_db_with_cards, test_settings):
    """xenon URL refuses connections -> the forever loop must serve ticks
    from the massive fake on the very next session (no 300s stall)."""
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    tick_flushed = asyncio.Event()

    async def massive_handler(ws):
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send(json.dumps(
                    [{"ev": "A", "sym": "TSLA", "c": 333.0, "e": 1779380400000}]
                ))
                await asyncio.sleep(0.5)
                tick_flushed.set()

    @contextmanager
    def repo_factory(role):
        yield repo

    async with websockets.serve(massive_handler, "127.0.0.1", 0) as massive_srv:
        m_port = massive_srv.sockets[0].getsockname()[1]
        settings = _settings(
            test_settings,
            xenon_ws_enabled=True,
            xenon_ws_url="ws://127.0.0.1:1",  # nothing listens here
            xenon_ws_port_file="",
            xenon_ws_retry_primary_seconds=3600.0,
            massive_ws_enabled=True,
            massive_ws_url=f"ws://127.0.0.1:{m_port}",
            massive_ws_flush_interval_seconds=0.1,
        )
        task = asyncio.create_task(run_consumer_forever(settings, repo_factory))
        try:
            await asyncio.wait_for(tick_flushed.wait(), timeout=10.0)
            await asyncio.sleep(0.3)  # one more flush window
        finally:
            task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await task

    q = repo.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("333.0")
    state = repo.get_ws_consumer_state()
    assert state.active_source == "massive.com_ws"


@pytest.mark.asyncio
async def test_massive_session_switches_back_when_xenon_recovers(
    seeded_db_with_cards, test_settings
):
    """While the massive fallback session streams, a xenon server comes up;
    the re-probe must cancel the massive session and the next session must
    write xenon-sourced ticks."""
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    xenon_tick = asyncio.Event()

    async def massive_handler(ws):
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                while True:  # stream forever until cancelled
                    await ws.send(json.dumps(
                        [{"ev": "A", "sym": "TSLA", "c": 333.0, "e": 1779380400000}]
                    ))
                    await asyncio.sleep(0.2)

    async def xenon_handler(ws):
        await ws.send(STATUS_OK)
        async for msg in ws:
            if json.loads(msg).get("action") == "subscribe":
                while True:
                    await ws.send(_xenon_batch({"TSLA": 444.0}))
                    xenon_tick.set()
                    await asyncio.sleep(0.2)

    @contextmanager
    def repo_factory(role):
        yield repo

    async with websockets.serve(massive_handler, "127.0.0.1", 0) as massive_srv:
        m_port = massive_srv.sockets[0].getsockname()[1]
        async with websockets.serve(xenon_handler, "127.0.0.1", 0) as xenon_srv:
            x_port = xenon_srv.sockets[0].getsockname()[1]
            settings = _settings(
                test_settings,
                xenon_ws_enabled=True,
                # Trick: first xenon attempt targets a dead port -> fallback;
                # the probe targets the SAME url, so bring xenon up on that
                # port only after fallback engaged. Simpler: short retry +
                # live server from the start but make the FIRST connect fail
                # by starting the forever-loop before the xenon server exists.
                xenon_ws_url=f"ws://127.0.0.1:{x_port}",
                xenon_ws_port_file="",
                xenon_ws_retry_primary_seconds=0.5,
                massive_ws_enabled=True,
                massive_ws_url=f"ws://127.0.0.1:{m_port}",
                massive_ws_flush_interval_seconds=0.1,
            )
            task = asyncio.create_task(run_consumer_forever(settings, repo_factory))
            try:
                await asyncio.wait_for(xenon_tick.wait(), timeout=15.0)
                await asyncio.sleep(0.5)  # let a flush land
            finally:
                task.cancel()
                with contextlib.suppress(asyncio.CancelledError):
                    await task

    q = repo.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("444.0")
    state = repo.get_ws_consumer_state()
    assert state.active_source == "xenon_ws"
```

(Adapt `_settings`/`test_settings` to the actual Settings construction pattern used by `tests/integration/worker/test_massive_ws_consumer.py` — whatever it does to get a Settings wired at the test DB. For the recovery test, the simple deterministic shape is: start `run_consumer_forever` with xenon pointing at a port with no listener, wait for the massive `active_source`, then start the xenon server on that exact port (bind it lazily with `websockets.serve(..., x_port)` after fallback is observed) and wait for `xenon_tick`. Implement it that way — reserve the port by binding/closing a socket first.)

- [ ] **Step 2: Run** → FAIL (forever-loop never tries xenon).

- [ ] **Step 3: Implement.**

3a. Probe helper:

```python
async def _xenon_probe_loop(settings: Settings) -> None:
    """Block until xenon accepts a connection AND reports ib_connected.

    Runs inside a massive fallback session (raced via asyncio.wait). First
    probe waits a full retry interval — we just failed xenon, don't hammer it.
    Returns (completes) only on success; probe errors loop forever.
    """
    while True:
        await asyncio.sleep(settings.xenon_ws_retry_primary_seconds)
        url = discover_xenon_ws_url(settings.xenon_ws_url, settings.xenon_ws_port_file)
        try:
            async with XenonWsClient(url, open_timeout=5.0):
                pass  # handshake (status ib_connected=true) is the success test
            logger.info("xenon ws probe succeeded at %s", url)
            return
        except (XenonFeedUnavailable, OSError, asyncio.TimeoutError) as exc:
            logger.debug("xenon ws probe failed: %s", repr(exc))
```

3b. Rewrite `run_consumer_forever`'s body. Keep: shared `TickBuffer`, backoff state machine, psycopg/`BaseExceptionGroup` error classification. Add provider choice + xenon failure classification + fallback race:

```python
async def run_consumer_forever(settings: Settings, repo_factory) -> None:
    """<existing docstring> plus:

    Provider selection (xenon primary / massive fallback): when
    ``xenon_ws_enabled``, each session attempts xenon first unless a recent
    xenon failure blocked it (``xenon_ws_retry_primary_seconds`` window).
    Massive fallback sessions race a probe task; when xenon recovers the
    massive session is cancelled (shared TickBuffer carries pending ticks
    across the switch — bounded loss is the same ~flush-interval window as
    the documented SIGTERM path) and the next session is xenon.
    """
    buffer = TickBuffer()
    backoff = settings.massive_ws_reconnect_backoff_initial_seconds
    massive_available = (
        settings.massive_ws_enabled and settings.massive_api_key is not None
    )
    xenon_blocked_until = 0.0  # time.monotonic() deadline; 0 = try now
    while True:
        use_xenon = settings.xenon_ws_enabled and (
            time.monotonic() >= xenon_blocked_until
        )
        if not use_xenon and not massive_available:
            # xenon-only deployment during its retry-block window.
            wait = max(xenon_blocked_until - time.monotonic(), backoff)
            logger.warning(
                "no WS feed available (xenon blocked, massive disabled); "
                "retrying xenon in %.0fs", wait,
            )
            await asyncio.sleep(wait)
            xenon_blocked_until = 0.0
            continue
        try:
            with (
                repo_factory("writer") as writer_repo,
                repo_factory("reader") as reader_repo,
            ):
                desired = await asyncio.to_thread(
                    lambda: {w.ticker for w in reader_repo.list_active_watchlist()}
                )
                if use_xenon:
                    url = discover_xenon_ws_url(
                        settings.xenon_ws_url, settings.xenon_ws_port_file
                    )
                    final_ok = await run_consumer_once(
                        ws_url=url,
                        api_key="",
                        channel=settings.massive_ws_channel,
                        tickers=desired,
                        writer_repo=writer_repo,
                        reader_repo=reader_repo,
                        flush_interval_seconds=settings.massive_ws_flush_interval_seconds,
                        subscription_poll_interval_seconds=settings.massive_ws_watchlist_poll_interval_seconds,
                        buffer=buffer,
                        client=XenonWsClient(url),
                        source_tag="xenon_ws",
                        quiet_failover_seconds=settings.xenon_ws_quiet_failover_seconds,
                        rth_tz=settings.rth_tz,
                    )
                else:
                    session = asyncio.create_task(
                        run_consumer_once(
                            ws_url=settings.massive_ws_url,
                            api_key=settings.massive_api_key.get_secret_value(),
                            channel=settings.massive_ws_channel,
                            tickers=desired,
                            writer_repo=writer_repo,
                            reader_repo=reader_repo,
                            flush_interval_seconds=settings.massive_ws_flush_interval_seconds,
                            subscription_poll_interval_seconds=settings.massive_ws_watchlist_poll_interval_seconds,
                            buffer=buffer,
                        ),
                        name="massive_fallback_session",
                    )
                    if settings.xenon_ws_enabled:
                        probe = asyncio.create_task(
                            _xenon_probe_loop(settings), name="xenon_probe"
                        )
                        try:
                            done, _pending = await asyncio.wait(
                                {session, probe},
                                return_when=asyncio.FIRST_COMPLETED,
                            )
                        except asyncio.CancelledError:
                            session.cancel()
                            probe.cancel()
                            with contextlib.suppress(BaseException):
                                await session
                            with contextlib.suppress(BaseException):
                                await probe
                            raise
                        if session in done:
                            probe.cancel()
                            with contextlib.suppress(asyncio.CancelledError):
                                await probe
                            final_ok = session.result()  # re-raises session errors
                        else:
                            # Xenon recovered: unwind the massive session.
                            # Cancellation here is the documented SIGTERM-shaped
                            # path — pending ticks merge back into the shared
                            # buffer; loss bounded to ~1 flush interval.
                            session.cancel()
                            with contextlib.suppress(
                                asyncio.CancelledError, Exception
                            ):
                                await session
                            xenon_blocked_until = 0.0
                            logger.info(
                                "xenon primary recovered; leaving massive fallback"
                            )
                            continue
                    else:
                        final_ok = await session
            if final_ok:
                backoff = settings.massive_ws_reconnect_backoff_initial_seconds
            await asyncio.sleep(backoff)
            if not final_ok:
                backoff = min(
                    backoff * 2.0,
                    settings.massive_ws_reconnect_backoff_max_seconds,
                )
            continue
        except (XenonFeedUnavailable, OSError, asyncio.TimeoutError) as exc:
            if use_xenon:
                xenon_blocked_until = (
                    time.monotonic() + settings.xenon_ws_retry_primary_seconds
                )
                logger.warning(
                    "xenon ws unavailable (%s); falling back to massive for %.0fs",
                    repr(exc),
                    settings.xenon_ws_retry_primary_seconds,
                )
                continue  # massive attempt immediately, no backoff growth
            logger.exception(
                "ws consumer crashed: %s; backoff=%.1fs", repr(exc), backoff
            )
            try:
                with repo_factory("writer") as err_repo:
                    err_repo.record_ws_error(repr(exc), datetime.now(timezone.utc))
            except Exception:
                logger.exception("ws consumer: failed to record error to DB (ignored)")
        except psycopg.OperationalError:
            logger.exception("ws consumer: DB unreachable; backoff=%.1fs", backoff)
        except BaseExceptionGroup as eg:
            quiet, rest = eg.split(_FeedQuiet)
            if quiet is not None and use_xenon and rest is None:
                xenon_blocked_until = (
                    time.monotonic() + settings.xenon_ws_retry_primary_seconds
                )
                logger.warning(
                    "xenon ws went quiet; falling back to massive for %.0fs",
                    settings.xenon_ws_retry_primary_seconds,
                )
                continue
            op_errs, _rest = eg.split(psycopg.OperationalError)
            if op_errs is not None:
                logger.exception(
                    "ws consumer: DB error mid-session; backoff=%.1fs", backoff
                )
            else:
                logger.exception(
                    "ws consumer crashed: %s; backoff=%.1fs", repr(eg), backoff
                )
                try:
                    with repo_factory("writer") as err_repo:
                        err_repo.record_ws_error(repr(eg), datetime.now(timezone.utc))
                except Exception:
                    logger.exception(
                        "ws consumer: failed to record error to DB (ignored)"
                    )
        except Exception as exc:
            logger.exception(
                "ws consumer crashed: %s; backoff=%.1fs", repr(exc), backoff
            )
            try:
                with repo_factory("writer") as err_repo:
                    err_repo.record_ws_error(repr(exc), datetime.now(timezone.utc))
            except Exception:
                logger.exception("ws consumer: failed to record error to DB (ignored)")
        await asyncio.sleep(backoff)
        backoff = min(backoff * 2.0, settings.massive_ws_reconnect_backoff_max_seconds)
```

Ordering note: the `(XenonFeedUnavailable, OSError, asyncio.TimeoutError)` clause must precede `except Exception`; `psycopg.OperationalError` is an `Exception` subclass not in that tuple, so its dedicated clause still catches DB-connect failures (psycopg's `OperationalError` does NOT inherit `OSError`).

3c. `main()` gating:

```python
    settings = Settings.from_env()
    if not (settings.massive_ws_enabled or settings.xenon_ws_enabled):
        logger.warning("neither MASSIVE_WS_ENABLED nor XENON_WS_ENABLED is true; exiting")
        return 0
    if settings.massive_ws_enabled and settings.massive_api_key is None:
        if settings.xenon_ws_enabled:
            logger.warning(
                "MASSIVE_API_KEY missing — running xenon-only (no massive fallback)"
            )
        else:
            logger.error("MASSIVE_API_KEY is not set; cannot start WS consumer")
            return 1
```

(`run_consumer_forever`'s `massive_available` flag already degrades correctly.)

- [ ] **Step 4: Run** `uv run pytest tests/integration/worker/ -v` → PASS (new failover tests + all pre-existing consumer tests).

---

### Task 6: Docs + ops wiring

**Files:**
- Modify: `CLAUDE.md` (root — "What this is" + data-source line), `AGENTS.md` (keep in sync per standing rule)
- Modify: `src/uw_scan/worker/CLAUDE.md` (`massive_ws` process section)
- Modify: `src/uw_scan/sources/CLAUDE.md` (add `xenon_ws.py` entry)
- Modify: `.env.example` if present (check `ls -a`; add XENON_* keys commented)

- [ ] **Step 1: Root CLAUDE.md** — in "What this is", change the data-source sentence to: "UW (Unusual Whales) is the primary data source; xenon's IB realtime WS is the primary intraday spot feed (massive WS is the automatic fallback); massive.com supplies OHLC. **Never fall back to Yahoo.**" Add a short env table for `XENON_WS_ENABLED` / `XENON_WS_URL` / `XENON_WS_PORT_FILE` / `XENON_WS_RETRY_PRIMARY_SECONDS` / `XENON_WS_QUIET_FAILOVER_SECONDS` near the worker description, noting: MacBook dev points at the mini via `XENON_WS_URL=ws://100.66.147.98:8765`; mini prod uses the localhost default + port-file discovery; rotating any XENON_* env requires restarting the spot-WS consumer process (env frozen at fork).

- [ ] **Step 2: worker/CLAUDE.md** — update the `massive_ws` bullet: the process is now the spot WS consumer for BOTH feeds (module name retained for plist/dev.sh compat); describe primary/fallback + quiet watchdog + `active_source` health field; note `preserve_spot` now keys off `ws_spot_enabled` (either flag). sources/CLAUDE.md — add `xenon_ws.py` row mirroring the `massive_ws.py` entry, including the index-bucket mapping and "extend XENON_INDEX_SYMBOLS when the watchlist grows a new index".

- [ ] **Step 3: AGENTS.md** — mirror the root CLAUDE.md edits verbatim.

- [ ] **Step 4:** `bash scripts/migrate.sh` against the local dev DB (`option_wizard_local`) so the dev stack picks up 068 (test DBs run migrations per-fixture automatically).

---

### Task 7: Full verification

- [ ] **Step 1:** `uv run pytest` (full suite) → all green.
- [ ] **Step 2:** `cd web && npm run test` → green (types regen shouldn't break vitest, verify).
- [ ] **Step 3:** Lint/format per repo tooling (check `pyproject.toml` for ruff config; run `uv run ruff check src tests` + `uv run ruff format --check` if configured).
- [ ] **Step 4:** Live smoke (only if xenon reachable from this machine): `XENON_WS_ENABLED=true XENON_WS_URL=ws://100.66.147.98:8765 timeout 30 uv run python -m uw_scan.worker.massive_ws_consumer` against the LOCAL dev DB and watch for "xenon" log lines + `watchlist_card.spot_source='xenon_ws'` rows. If xenon is unreachable, verify the fallback log path instead.
- [ ] **Step 5:** Draft summary for the user; NO commit, NO PR until explicitly requested.

---

## Self-Review

- **Spec coverage:** subscribe-as-primary ✔ (Task 5 provider selection), massive substitute ✔ (fallback matrix), xenon protocol (symbols/indexes split, batch/price/status/error frames) ✔ (Task 2), port-file discovery ✔ (Task 2), Tailscale/remote URL ✔ (config + docs), greeks/fundamentals/contracts deliberately out of scope ✔.
- **Type consistency:** `discover_xenon_ws_url(configured_url, port_file)` consistent across Tasks 2/5; `run_consumer_once(client=, source_tag=, quiet_failover_seconds=, rth_tz=)` consistent across Tasks 3/5; `record_ws_connection_started(started_at, source)` consistent across Tasks 3/4.
- **Known judgment calls (flag in PR):** quiet-watchdog default 120 s matches `massive_ws_heartbeat_stale_after_seconds`; mid-session `ib_connected:false` does NOT failover immediately (avoids flapping on transient IB blips — watchdog is the backstop); massive-session cancel-on-recovery reuses the documented bounded-loss SIGTERM path.
