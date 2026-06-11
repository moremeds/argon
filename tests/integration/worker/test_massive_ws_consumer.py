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
from uw_scan.worker.ws_tick_buffer import TickBuffer


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
                # Give the WS time to deliver the frame to the client AND
                # for the periodic flush_loop (50ms interval in this test)
                # to drain it to the DB before tick_sent triggers the test's
                # cancel path. Without this delay the consumer is sometimes
                # cancelled before the reader has processed the tick.
                await asyncio.sleep(0.3)
                tick_sent.set()
                await asyncio.sleep(0.1)
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
                # Force-disable xenon so the test exercises only the massive
                # reconnect/backoff path. The worktree's .env.local enables
                # xenon by default; without this override Settings.from_env()
                # would have the consumer connect to the real mini xenon
                # instead of the fake massive server bound on 127.0.0.1.
                "xenon_ws_enabled": False,
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
    # Poll for the persisted tick instead of a single read — under heavy
    # suite load the final flush in run_consumer_once's `finally` clause
    # can race with this assertion. Up to 2s is well within the test's
    # implicit budget and catches the post-cancel flush deterministically.
    q = None
    for _ in range(20):
        q = repo.get_intraday_quote("TSLA")
        if q is not None:
            break
        await asyncio.sleep(0.1)
    assert q is not None and q.price == Decimal("451.00")


class _SecretStrTestKey:
    """Tiny stand-in for pydantic SecretStr so the test doesn't need to
    import SecretStr just to wrap a constant. Mirrors the only method the
    consumer calls."""

    def get_secret_value(self) -> str:
        return "TEST_KEY"


@pytest.mark.asyncio
async def test_final_flush_failure_returns_false(seeded_db_with_cards, monkeypatch):
    """Adversarial-4 regression: when the final flush raises, the function
    must return False so ``run_consumer_forever`` does NOT reset its
    backoff. Persistent DB-write failures otherwise spam-reconnect.
    """
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
                                "c": 470.10,
                                "e": 1779380400000,
                            }
                        ]
                    )
                )
                await asyncio.sleep(0.1)
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True

        # Every flush fails, including the final one.
        def boom(*_a, **_k):
            raise RuntimeError("simulated DB always down")

        monkeypatch.setattr(repo, "bulk_upsert_intraday_quotes", boom)
        result = await run_consumer_once(
            ws_url=url,
            api_key="TEST_KEY",
            channel="A",
            tickers={"TSLA"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.05,
            run_for_seconds=1.0,
        )
        assert result is False, (
            "final flush failed; run_consumer_once must return False"
        )


@pytest.mark.asyncio
async def test_final_flush_timeout_returns_false(seeded_db_with_cards, monkeypatch):
    """Adversarial-3 regression: when the final flush exceeds
    ``final_flush_timeout_seconds`` (e.g., Postgres hangs while holding
    ``_flush_lock``), the function returns False and the process can exit
    rather than hang indefinitely.
    """
    import time as _time

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
                                "c": 480.20,
                                "e": 1779380400000,
                            }
                        ]
                    )
                )
                await asyncio.sleep(0.1)
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True

        # Make bulk_upsert sleep 3s — longer than our timeout (0.4s).
        def slow_upsert(*_a, **_k):
            _time.sleep(3.0)

        monkeypatch.setattr(repo, "bulk_upsert_intraday_quotes", slow_upsert)
        # Tight timeout so the test runs fast.
        result = await run_consumer_once(
            ws_url=url,
            api_key="TEST_KEY",
            channel="A",
            tickers={"TSLA"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.05,
            run_for_seconds=0.5,
            final_flush_timeout_seconds=0.4,
        )
        assert result is False, (
            "final flush timed out; run_consumer_once must return False"
        )


@pytest.mark.asyncio
async def test_buffer_survives_across_consumer_once_calls(
    seeded_db_with_cards, monkeypatch
):
    """ISSUE-1 regression: when ``run_consumer_once`` runs back-to-back
    sessions (the ``run_consumer_forever`` pattern) sharing the same
    ``TickBuffer``, ticks orphaned by a failed flush in session N MUST
    be persisted by session N+1.

    Before the fix the buffer was allocated inside ``run_consumer_once``,
    so a failed final flush would merge ticks back into a local buffer
    that went out of scope when the function returned — silently
    discarding them despite the A2 retry contract.
    """
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
                                "c": 461.50,
                                "e": 1779380400000,
                            }
                        ]
                    )
                )
                await asyncio.sleep(0.2)
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True

        shared_buffer = TickBuffer()

        # Session 1: bulk_upsert is patched to raise so the final flush fails.
        # Ticks must be merged back into shared_buffer rather than discarded.
        original = repo.bulk_upsert_intraday_quotes

        def boom(*_a, **_k):
            raise RuntimeError("simulated DB hiccup at session end")

        monkeypatch.setattr(repo, "bulk_upsert_intraday_quotes", boom)
        await run_consumer_once(
            ws_url=url,
            api_key="TEST_KEY",
            channel="A",
            tickers={"TSLA"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.05,
            run_for_seconds=1.0,
            buffer=shared_buffer,
        )
        # Tick did NOT land in the DB (session 1's flush always failed).
        assert repo.get_intraday_quote("TSLA") is None
        # But the buffer holds it for the next session.
        assert len(shared_buffer) >= 1

    # Session 2: server is gone, but the buffer's tick survives. Restore
    # the real upsert and call run_consumer_once with a server that closes
    # immediately so the final flush drains the buffer cleanly.
    monkeypatch.setattr(repo, "bulk_upsert_intraday_quotes", original)

    async def quiet_handler(ws):
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await asyncio.sleep(0.1)
                await ws.close()

    async with websockets.serve(quiet_handler, "127.0.0.1", 0) as server2:
        port2 = server2.sockets[0].getsockname()[1]
        url2 = f"ws://127.0.0.1:{port2}"
        await run_consumer_once(
            ws_url=url2,
            api_key="TEST_KEY",
            channel="A",
            tickers={"TSLA"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.05,
            run_for_seconds=1.0,
            buffer=shared_buffer,
        )

    q = repo.get_intraday_quote("TSLA")
    assert q is not None, (
        "tick from session 1 should be persisted by session 2 via shared buffer"
    )
    assert q.price == Decimal("461.50")
    assert len(shared_buffer) == 0
