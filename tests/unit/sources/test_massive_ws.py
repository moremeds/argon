"""Unit tests for the massive.com WebSocket client + parser (Phase 2)."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest
import websockets

from uw_scan.sources.massive_ws import (
    MassiveWsClient,
    WsTick,
    parse_ws_message,
)

# ---- Parser tests ---------------------------------------------------------


def test_parse_ws_message_aggregate_per_second():
    """Per-second aggregate message — channel 'A.<TICKER>'."""
    raw = '[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000}]'
    ticks = parse_ws_message(raw)
    assert len(ticks) == 1
    assert ticks[0] == WsTick(
        ticker="AAPL",
        price=Decimal("189.42"),
        quoted_at=datetime(2026, 5, 21, 16, 20, tzinfo=timezone.utc),
        channel="A",
    )


def test_parse_ws_message_status_skipped():
    """Status messages (auth_success, subscribed) yield no ticks."""
    raw = '[{"ev":"status","status":"auth_success","message":"authenticated"}]'
    ticks = parse_ws_message(raw)
    assert ticks == []


def test_parse_ws_message_batched_array():
    """Massive batches multiple ticks per frame."""
    raw = (
        '[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000},'
        '{"ev":"A","sym":"MSFT","c":425.10,"e":1779380400000}]'
    )
    ticks = parse_ws_message(raw)
    assert len(ticks) == 2
    assert ticks[0].ticker == "AAPL"
    assert ticks[1].ticker == "MSFT"


def test_parse_ws_message_missing_fields_skipped():
    raw = '[{"ev":"A","sym":"AAPL"}]'  # no c / no e
    ticks = parse_ws_message(raw)
    assert ticks == []


def test_parse_ws_message_invalid_json_raises():
    with pytest.raises(ValueError):
        parse_ws_message("not json")


def test_parse_ws_message_per_minute_aggregate():
    """AM channel uses same shape as A."""
    raw = '[{"ev":"AM","sym":"AAPL","c":189.42,"e":1779380400000}]'
    ticks = parse_ws_message(raw)
    assert len(ticks) == 1
    assert ticks[0].channel == "AM"


def test_parse_ws_message_trade_message():
    """T channel uses 'p' for price and 't' for epoch."""
    raw = '[{"ev":"T","sym":"AAPL","p":189.42,"t":1779380400000}]'
    ticks = parse_ws_message(raw)
    assert len(ticks) == 1
    assert ticks[0].price == Decimal("189.42")
    assert ticks[0].channel == "T"


def test_parse_ws_message_dict_not_list_returns_empty():
    """If broker sends a bare dict (non-spec), don't crash — return []."""
    raw = '{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000}'
    assert parse_ws_message(raw) == []


def test_parse_ws_message_extra_fields_ignored():
    """Real massive frames carry many extra fields (op, vw, av, etc.)."""
    raw = (
        '[{"ev":"A","sym":"AAPL","v":140,"av":7208000,"op":301.055,'
        '"vw":302.3797,"o":302.545,"c":302.545,"h":302.545,"l":302.545,'
        '"a":301.9198,"z":4,"s":1779374146000,"e":1779374147000}]'
    )
    ticks = parse_ws_message(raw)
    assert len(ticks) == 1
    assert ticks[0].price == Decimal("302.545")


def test_parse_ws_message_per_row_failure_does_not_kill_batch():
    """A4: one bad row must not take down the whole frame."""
    raw = (
        '[{"ev":"A","sym":"AAPL","c":"not-a-number","e":1779380400000},'
        '{"ev":"A","sym":"MSFT","c":425.10,"e":1779380400000}]'
    )
    ticks = parse_ws_message(raw)
    assert len(ticks) == 1
    assert ticks[0].ticker == "MSFT"


def test_parse_ws_message_bad_epoch_skipped():
    raw = '[{"ev":"A","sym":"AAPL","c":189.42,"e":"not-an-int"}]'
    ticks = parse_ws_message(raw)
    assert ticks == []


def test_parse_ws_message_bytes_frame_decoded():
    raw = b'[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000}]'
    ticks = parse_ws_message(raw)
    assert len(ticks) == 1
    assert ticks[0].ticker == "AAPL"


def test_parse_ws_message_non_utf8_bytes_raises():
    raw = b"\xff\xfe\x00bad"
    with pytest.raises(ValueError):
        parse_ws_message(raw)


# ---- Client lifecycle tests ----------------------------------------------


@pytest.mark.asyncio
async def test_client_bypasses_system_proxy(monkeypatch):
    """The dedicated market-data stream must not inherit macOS proxy settings."""
    connect_kwargs: dict[str, object] = {}

    class FakeWebSocket:
        async def send(self, _message: str) -> None:
            return None

        async def recv(self) -> str:
            return '[{"ev":"status","status":"auth_success"}]'

        async def close(self) -> None:
            return None

    async def fake_connect(_url: str, **kwargs):
        connect_kwargs.update(kwargs)
        return FakeWebSocket()

    monkeypatch.setattr(websockets, "connect", fake_connect)

    async with MassiveWsClient("wss://delayed.massive.com/stocks", "TEST_KEY"):
        pass

    assert connect_kwargs["proxy"] is None


@pytest.mark.asyncio
async def test_client_authenticates_and_subscribes():
    """Spin up a fake WS server, verify auth + subscribe messages are sent."""
    received: list[str] = []

    async def handler(ws):
        async for msg in ws:
            received.append(msg)
            data = json.loads(msg)
            if data.get("action") == "auth":
                await ws.send('[{"ev":"status","status":"auth_success"}]')
            elif data.get("action") == "subscribe":
                await ws.send('[{"ev":"A","sym":"AAPL","c":189.42,"e":1779380400000}]')
                await ws.close()

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        async with MassiveWsClient(url, "TEST_KEY") as client:
            await client.subscribe(["A.AAPL"])
            ticks = [t async for t in client.ticks()]

    assert len(received) == 2
    auth = json.loads(received[0])
    assert auth == {"action": "auth", "params": "TEST_KEY"}
    sub = json.loads(received[1])
    assert sub == {"action": "subscribe", "params": "A.AAPL"}
    assert len(ticks) == 1
    assert ticks[0].ticker == "AAPL"


@pytest.mark.asyncio
async def test_client_raises_when_auth_rejected():
    """R13: auth failure must raise — don't silently subscribe to nothing."""

    async def handler(ws):
        async for _ in ws:
            await ws.send('[{"ev":"status","status":"auth_failed"}]')
            return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        with pytest.raises(RuntimeError, match="auth"):
            async with MassiveWsClient(url, "BAD_KEY"):
                pass


@pytest.mark.asyncio
async def test_client_subscribe_is_idempotent():
    """Re-subscribing to an existing channel must not resend."""
    received: list[str] = []

    async def handler(ws):
        try:
            async for msg in ws:
                received.append(msg)
                data = json.loads(msg)
                if data.get("action") == "auth":
                    await ws.send('[{"ev":"status","status":"auth_success"}]')
        except websockets.exceptions.ConnectionClosed:
            return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        async with MassiveWsClient(url, "TEST_KEY") as client:
            await client.subscribe(["A.AAPL"])
            await client.subscribe(["A.AAPL"])  # idempotent
            await asyncio.sleep(0.05)

    # auth + 1 subscribe, not 2
    actions = [json.loads(m).get("action") for m in received]
    assert actions.count("subscribe") == 1


@pytest.mark.asyncio
async def test_client_accepts_connected_then_auth_success():
    """Massive sends 'connected' before 'auth_success'. The client must skip the
    initial connected frame and accept the second."""

    async def handler(ws):
        async for msg in ws:
            data = json.loads(msg)
            if data.get("action") == "auth":
                # First frame: connected (not auth_success).
                await ws.send(
                    '[{"ev":"status","status":"connected","message":"Connected"}]'
                )
                # Second frame: the real auth_success.
                await ws.send('[{"ev":"status","status":"auth_success"}]')
                return

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        url = f"ws://127.0.0.1:{port}"
        async with MassiveWsClient(url, "TEST_KEY"):
            pass  # if we got here without raising, auth flow worked
