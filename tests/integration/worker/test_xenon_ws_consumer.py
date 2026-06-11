"""Integration: run_consumer_once with an injected XenonWsClient.

Same fake-server style as test_massive_ws_consumer.py, speaking xenon's
protocol (status handshake + batch frames) instead of massive's.
"""

from __future__ import annotations

import asyncio
import json
from decimal import Decimal

import pytest
import websockets

from uw_scan.sources.xenon_ws import XenonFeedUnavailable, XenonWsClient
from uw_scan.worker.massive_ws_consumer import _FeedQuiet, run_consumer_once

STATUS_OK = json.dumps({"type": "status", "ib_connected": True, "subscriptions": []})


def _batch(prices: dict[str, float]) -> str:
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


@pytest.mark.asyncio
async def test_xenon_session_persists_ticks_with_xenon_source(seeded_db_with_cards):
    """Fake xenon server: status handshake, batch of 2 ticks on subscribe,
    then close. Both ticks must persist with source tags = xenon_ws."""
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
    assert received[0]["indexes"] == []
    q = repo.get_intraday_quote("TSLA")
    assert q is not None and q.price == Decimal("189.42")
    card = repo.get_watchlist_card("TSLA")
    assert card is not None and card.spot_source == "xenon_ws"
    state = repo.get_ws_consumer_state()
    assert state is not None and state.active_source == "xenon_ws"
    assert state.ticks_flushed >= 2


@pytest.mark.asyncio
async def test_quiet_watchdog_raises_feed_quiet(seeded_db_with_cards, monkeypatch):
    """Server completes the handshake but never sends a tick; the quiet
    watchdog must unwind the session with _FeedQuiet. The market-session
    gate is forced open via monkeypatch so the test is wall-clock-stable."""
    import uw_scan.worker.massive_ws_consumer as consumer_mod

    monkeypatch.setattr(consumer_mod, "current_market_date", lambda now, tz: now.date())

    async def handler(ws):
        await ws.send(STATUS_OK)
        async for _ in ws:
            pass  # swallow subscribe, send no ticks

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


@pytest.mark.asyncio
async def test_zero_tick_session_raises_xenon_feed_unavailable(
    seeded_db_with_cards, monkeypatch
):
    """Tribunal Codex P1: a xenon server that completes the handshake but
    closes before delivering any ticks must NOT be reported as a successful
    session — run_consumer_forever would otherwise immediately retry xenon
    and a flapping server would freeze spots indefinitely. The post-session
    gate raises XenonFeedUnavailable so the forever-loop blocks xenon for
    the retry window."""
    import uw_scan.worker.massive_ws_consumer as consumer_mod

    monkeypatch.setattr(consumer_mod, "current_market_date", lambda now, tz: now.date())

    async def handler(ws):
        await ws.send(STATUS_OK)
        # Read subscribe, drop the connection without ever pushing a batch.
        try:
            await asyncio.wait_for(ws.recv(), timeout=0.4)
        except asyncio.TimeoutError:
            pass
        await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        repo = seeded_db_with_cards
        repo._conn.autocommit = True
        with pytest.raises(XenonFeedUnavailable):
            await run_consumer_once(
                ws_url=url,
                api_key="",
                channel="A",
                tickers={"TSLA"},
                writer_repo=repo,
                reader_repo=repo,
                flush_interval_seconds=0.1,
                run_for_seconds=5.0,
                client=XenonWsClient(url),
                source_tag="xenon_ws",
                quiet_failover_seconds=120.0,
            )


@pytest.mark.asyncio
async def test_massive_default_records_massive_active_source(seeded_db_with_cards):
    """Default (no client injected) keeps the massive path byte-identical and
    records active_source = massive.com_ws."""

    async def handler(ws):
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send(
                    json.dumps(
                        [{"ev": "A", "sym": "TSLA", "c": 189.42, "e": 1779380400000}]
                    )
                )
                await asyncio.sleep(0.3)
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        repo = seeded_db_with_cards
        repo._conn.autocommit = True
        await run_consumer_once(
            ws_url=f"ws://127.0.0.1:{port}",
            api_key="TEST_KEY",
            channel="A",
            tickers={"TSLA"},
            writer_repo=repo,
            reader_repo=repo,
            flush_interval_seconds=0.1,
            run_for_seconds=1.0,
        )

    state = repo.get_ws_consumer_state()
    assert state is not None and state.active_source == "massive.com_ws"
    card = repo.get_watchlist_card("TSLA")
    assert card is not None and card.spot_source == "massive.com_ws"
