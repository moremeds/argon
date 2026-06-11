"""Failover semantics: xenon down -> massive fallback; xenon recovery ->
switch back via the in-session probe.

Same in-process fake-server style as test_massive_ws_consumer.py. The
recovery test drives the switch through the port-file discovery mechanism
(write /tmp-style port file once the xenon fake is up), so it covers
``discover_xenon_ws_url`` end-to-end as well.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
from contextlib import contextmanager
from decimal import Decimal

import pytest
import websockets

from uw_scan.config import Settings
from uw_scan.worker.massive_ws_consumer import (
    _xenon_probe_loop,
    run_consumer_forever,
)

STATUS_OK = json.dumps({"type": "status", "ib_connected": True, "subscriptions": []})


class _SecretStrTestKey:
    def get_secret_value(self) -> str:
        return "TEST_KEY"


def _xenon_batch(prices: dict[str, float]) -> str:
    return json.dumps(
        {
            "type": "batch",
            "updates": {
                sym: {
                    "symbol": sym,
                    "last": px,
                    "timestamp": "2026-06-11T14:31:43.838Z",
                }
                for sym, px in prices.items()
            },
        }
    )


def _massive_handler_streaming(price: float, tick_seen: asyncio.Event):
    async def handler(ws):
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                while True:
                    await ws.send(
                        json.dumps(
                            [{"ev": "A", "sym": "TSLA", "c": price, "e": 1779380400000}]
                        )
                    )
                    tick_seen.set()
                    await asyncio.sleep(0.2)

    return handler


@pytest.mark.asyncio
async def test_xenon_down_falls_back_to_massive(seeded_db_with_cards):
    """Nothing listens on the xenon URL -> the very next session must be
    massive (no retry-window stall) and persist massive-sourced ticks."""
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    tick_seen = asyncio.Event()

    @contextmanager
    def _repo_factory(role: str):
        yield repo

    handler = _massive_handler_streaming(333.0, tick_seen)
    async with websockets.serve(handler, "127.0.0.1", 0) as massive_srv:
        m_port = massive_srv.sockets[0].getsockname()[1]
        settings = Settings.from_env().model_copy(
            update={
                "xenon_ws_enabled": True,
                "xenon_ws_url": "ws://127.0.0.1:1",  # nothing listens here
                "xenon_ws_port_file": "",
                "xenon_ws_retry_primary_seconds": 3600.0,
                "massive_api_key": _SecretStrTestKey(),
                "massive_ws_enabled": True,
                "massive_ws_url": f"ws://127.0.0.1:{m_port}",
                "massive_ws_channel": "A",
                "massive_ws_flush_interval_seconds": 0.1,
                "massive_ws_watchlist_poll_interval_seconds": 0.5,
                "massive_ws_reconnect_backoff_initial_seconds": 0.05,
                "massive_ws_reconnect_backoff_max_seconds": 0.5,
            }
        )
        consumer_task = asyncio.create_task(
            run_consumer_forever(settings, _repo_factory)
        )
        try:
            await asyncio.wait_for(tick_seen.wait(), timeout=10.0)
            await asyncio.sleep(0.4)  # let a periodic flush land
        finally:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

    q = None
    for _ in range(20):
        q = repo.get_intraday_quote("TSLA")
        if q is not None:
            break
        await asyncio.sleep(0.1)
    assert q is not None and q.price == Decimal("333.0")
    state = repo.get_ws_consumer_state()
    assert state is not None and state.active_source == "massive.com_ws"


@pytest.mark.asyncio
async def test_massive_session_switches_back_when_xenon_recovers(
    seeded_db_with_cards, tmp_path
):
    """While the massive fallback session streams, xenon comes up (announced
    via the port file); the probe must unwind the massive session and the
    next session must write xenon-sourced ticks."""
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    massive_tick = asyncio.Event()
    xenon_tick = asyncio.Event()
    port_file = tmp_path / "xenon-ib-realtime.json"  # not written yet

    async def xenon_handler(ws):
        await ws.send(STATUS_OK)
        async for msg in ws:
            if json.loads(msg).get("action") == "subscribe":
                while True:
                    await ws.send(_xenon_batch({"TSLA": 444.0}))
                    xenon_tick.set()
                    await asyncio.sleep(0.2)

    @contextmanager
    def _repo_factory(role: str):
        yield repo

    massive_handler = _massive_handler_streaming(333.0, massive_tick)
    async with websockets.serve(massive_handler, "127.0.0.1", 0) as massive_srv:
        m_port = massive_srv.sockets[0].getsockname()[1]
        settings = Settings.from_env().model_copy(
            update={
                "xenon_ws_enabled": True,
                # Dead configured port; recovery is announced via port file.
                "xenon_ws_url": "ws://127.0.0.1:1",
                "xenon_ws_port_file": str(port_file),
                "xenon_ws_retry_primary_seconds": 0.3,
                "massive_api_key": _SecretStrTestKey(),
                "massive_ws_enabled": True,
                "massive_ws_url": f"ws://127.0.0.1:{m_port}",
                "massive_ws_channel": "A",
                "massive_ws_flush_interval_seconds": 0.1,
                "massive_ws_watchlist_poll_interval_seconds": 0.5,
                "massive_ws_reconnect_backoff_initial_seconds": 0.05,
                "massive_ws_reconnect_backoff_max_seconds": 0.5,
            }
        )
        consumer_task = asyncio.create_task(
            run_consumer_forever(settings, _repo_factory)
        )
        try:
            # Phase 1: fallback engaged, massive ticks flowing.
            await asyncio.wait_for(massive_tick.wait(), timeout=10.0)
            # Phase 2: xenon comes up; announce it through the port file.
            async with websockets.serve(xenon_handler, "127.0.0.1", 0) as xenon_srv:
                x_port = xenon_srv.sockets[0].getsockname()[1]
                port_file.write_text(json.dumps({"port": x_port, "pid": 1}))
                await asyncio.wait_for(xenon_tick.wait(), timeout=10.0)
                await asyncio.sleep(0.4)  # let a xenon flush land
        finally:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

    q = None
    for _ in range(20):
        q = repo.get_intraday_quote("TSLA")
        if q is not None and q.price == Decimal("444.0"):
            break
        await asyncio.sleep(0.1)
    assert q is not None and q.price == Decimal("444.0")
    state = repo.get_ws_consumer_state()
    assert state is not None and state.active_source == "xenon_ws"


@pytest.mark.asyncio
async def test_xenon_probe_loop_returns_on_handshake_success():
    """Direct test of _xenon_probe_loop: it must sleep first (we just
    failed xenon — don't hammer), then handshake-test, and return on
    success. Failure-loop semantics are covered by the recovery test
    above; here we pin the success path with the smallest possible
    retry interval."""

    async def handler(ws):
        await ws.send(STATUS_OK)
        # Hold open briefly so the probe's `async with XenonWsClient` can
        # complete __aenter__ + status read + __aexit__.
        await asyncio.sleep(0.5)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        settings = Settings.from_env().model_copy(
            update={
                "xenon_ws_enabled": True,
                "xenon_ws_url": f"ws://127.0.0.1:{port}",
                "xenon_ws_port_file": "",
                # Tiny retry interval — verify "sleep first, then probe"
                # without slowing the test.
                "xenon_ws_retry_primary_seconds": 0.2,
            }
        )
        start = asyncio.get_event_loop().time()
        await asyncio.wait_for(_xenon_probe_loop(settings), timeout=3.0)
        elapsed = asyncio.get_event_loop().time() - start

    # The loop must wait at least one retry interval before probing
    # (matches the spec: don't hammer xenon after a recent failure).
    assert elapsed >= 0.2


@pytest.mark.asyncio
async def test_xenon_probe_loop_keeps_retrying_after_handshake_failure():
    """_xenon_probe_loop must NOT exit on handshake failure — it loops
    until success. ``ib_connected: false`` at connect raises
    XenonFeedUnavailable inside the probe; the probe must log + retry."""
    attempts = [0]

    async def handler(ws):
        attempts[0] += 1
        # First two attempts: ib_connected=false. Third: ib_connected=true.
        ib_connected = attempts[0] >= 3
        await ws.send(
            json.dumps(
                {
                    "type": "status",
                    "ib_connected": ib_connected,
                    "subscriptions": [],
                }
            )
        )
        await asyncio.sleep(0.5)

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        settings = Settings.from_env().model_copy(
            update={
                "xenon_ws_enabled": True,
                "xenon_ws_url": f"ws://127.0.0.1:{port}",
                "xenon_ws_port_file": "",
                "xenon_ws_retry_primary_seconds": 0.1,
            }
        )
        await asyncio.wait_for(_xenon_probe_loop(settings), timeout=5.0)

    # First 2 attempts must have failed (ib_connected=false), 3rd succeeded.
    assert attempts[0] >= 3
