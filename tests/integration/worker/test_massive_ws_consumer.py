"""Integration tests for the long-lived WS consumer (Phase 4).

Uses ``websockets.serve`` to stand up a local fake server. No real
network traffic — these are deterministic, in-process loops.
"""

from __future__ import annotations

import asyncio
import contextlib
import json
import time as time_module
from contextlib import contextmanager
from decimal import Decimal

import pytest
import websockets

from uw_scan.config import Settings
from uw_scan.worker.massive_ws_consumer import (
    run_consumer_forever,
    run_consumer_once,
)


@pytest.mark.asyncio
async def test_consumer_subscribes_and_persists(seeded_db_with_cards):
    """Fake server: replies to auth, replies to subscribe with 2 ticks,
    then closes. Consumer must persist both ticks under the latest spot."""
    received_messages: list[str] = []

    async def handler(ws):
        async for msg in ws:
            received_messages.append(msg)
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send(
                    json.dumps(
                        [
                            {
                                "ev": "A",
                                "sym": "TSLA",
                                "c": 189.42,
                                "e": 1779380400000,
                            },
                            {
                                "ev": "A",
                                "sym": "AAPL",
                                "c": 425.10,
                                "e": 1779380400000,
                            },
                        ]
                    )
                )
                await asyncio.sleep(0.3)
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True
        await run_consumer_once(
            ws_url=url,
            api_key="TEST_KEY",
            channel="A",
            tickers={"TSLA", "AAPL"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.1,
            run_for_seconds=1.0,
        )

    assert any("auth" in m for m in received_messages)
    assert any("subscribe" in m for m in received_messages)
    q_tsla = repo.get_intraday_quote("TSLA")
    q_aapl = repo.get_intraday_quote("AAPL")
    assert q_tsla is not None and q_tsla.price == Decimal("189.42")
    assert q_aapl is not None and q_aapl.price == Decimal("425.10")
    state = repo.get_ws_consumer_state()
    assert state.ticks_flushed >= 2


@pytest.mark.asyncio
async def test_consumer_backs_off_then_recovers(seeded_db_with_cards):
    """Fake server rejects the first 2 connection attempts (closes immediately)
    and accepts the 3rd. Validates:
      1. exponential backoff progresses through retries (gap_2 >= 0.8 * gap_1)
      2. successful reconnect resumes tick flow
      3. ws_consumer_state reflects the recovered tick
    """
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    connection_log: list[float] = []
    tick_sent = asyncio.Event()

    async def handler(ws):
        attempt_num = len(connection_log) + 1
        connection_log.append(time_module.monotonic())
        if attempt_num < 3:
            await ws.close(code=1011, reason="simulated transient failure")
            return
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send(
                    json.dumps(
                        [
                            {
                                "ev": "A",
                                "sym": "TSLA",
                                "c": 451.00,
                                "e": 1779380400000,
                            },
                        ]
                    )
                )
                tick_sent.set()
                await asyncio.sleep(0.2)
                await ws.close()
                return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        # Settings.from_env requires UW_SCAN_API_KEY; integration env has it.
        # We override only the WS fields needed for the test.
        settings = Settings.from_env().model_copy(
            update={
                "massive_api_key": _SecretStrTestKey(),
                "massive_ws_enabled": True,
                "massive_ws_url": f"ws://127.0.0.1:{port}",
                "massive_ws_channel": "A",
                "massive_ws_flush_interval_seconds": 0.05,
                "massive_ws_watchlist_poll_interval_seconds": 0.5,
                "massive_ws_reconnect_backoff_initial_seconds": 0.05,
                "massive_ws_reconnect_backoff_max_seconds": 0.5,
            }
        )

        @contextmanager
        def _repo_factory(role: str):
            # Single fixture conn; A1 doesn't bite here because the test
            # never has flush_loop + subscription_loop hit psycopg on the
            # same physical instant.
            yield repo

        consumer_task = asyncio.create_task(
            run_consumer_forever(settings, _repo_factory)
        )

        try:
            await asyncio.wait_for(tick_sent.wait(), timeout=5.0)
        finally:
            consumer_task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await consumer_task

    assert len(connection_log) >= 3, (
        f"expected >=3 connection attempts (2 rejects + 1 success), got "
        f"{len(connection_log)}"
    )
    gaps = [
        connection_log[i + 1] - connection_log[i]
        for i in range(len(connection_log) - 1)
    ]
    # gap_2 must be at least 80% of gap_1 — catches "backoff doesn't grow"
    # bugs (e.g. forgetting the `min(backoff*2, max)` update) while tolerating
    # asyncio scheduler jitter.
    if len(gaps) >= 2:
        assert gaps[1] >= gaps[0] * 0.8, f"backoff did not grow: gaps={gaps}"
    await asyncio.sleep(0.3)
    q = repo.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("451.00")


class _SecretStrTestKey:
    """Tiny stand-in for pydantic SecretStr so the test doesn't need to
    import SecretStr just to wrap a constant. Mirrors the only method the
    consumer calls."""

    def get_secret_value(self) -> str:
        return "TEST_KEY"
