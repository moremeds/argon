"""Unit tests for the xenon IB realtime WS client (parser + lifecycle).

Mirrors test_massive_ws.py: pure-function parser cases plus client lifecycle
against an in-process ``websockets.serve`` fake. No real network traffic.
"""

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
            "SPX": {
                "symbol": "SPX",
                "last": 7293.21,
                "timestamp": "2026-06-11T14:31:43.838Z",
            },
            "HYG": {
                "symbol": "HYG",
                "last": 79.55,
                "timestamp": "2026-06-11T14:31:43.901Z",
            },
            "TSLA_20261218_320_C": {
                "symbol": "TSLA_20261218_320_C",
                "last": 12.5,
                "timestamp": "2026-06-11T14:31:43.9Z",
            },
            "QUIET": {
                "symbol": "QUIET",
                "last": None,
                "timestamp": "2026-06-11T14:31:43.9Z",
            },
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
        {
            "type": "price",
            "symbol": "AAPL",
            "data": {
                "symbol": "AAPL",
                "last": 245.5,
                "timestamp": "2026-06-11T14:31:43.838Z",
            },
        }
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
    err = parse_xenon_message(
        json.dumps({"type": "error", "message": "IB not connected"})
    )
    assert err.kind == "error" and err.error == "IB not connected"


def test_parse_bad_row_does_not_kill_frame() -> None:
    raw = json.dumps(
        {
            "type": "batch",
            "updates": {
                "BAD": {"last": "not-a-number", "timestamp": "2026-06-11T14:31:43.9Z"},
                "OK": {"last": 1.5, "timestamp": "2026-06-11T14:31:43.9Z"},
            },
        }
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
    assert (
        discover_xenon_ws_url("ws://127.0.0.1:8765", str(pf)) == "ws://127.0.0.1:9001"
    )
    # non-localhost host: the port file is some OTHER machine's state — ignore
    assert (
        discover_xenon_ws_url("ws://100.66.147.98:8765", str(pf))
        == "ws://100.66.147.98:8765"
    )
    # missing / malformed / disabled fall back to the configured URL
    assert (
        discover_xenon_ws_url("ws://127.0.0.1:8765", str(tmp_path / "nope.json"))
        == "ws://127.0.0.1:8765"
    )
    (tmp_path / "bad.json").write_text("{")
    assert (
        discover_xenon_ws_url("ws://127.0.0.1:8765", str(tmp_path / "bad.json"))
        == "ws://127.0.0.1:8765"
    )
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
async def test_client_raises_when_no_status_frame() -> None:
    async def handler(ws):
        await asyncio.sleep(1)  # silent server — no status handshake

    async with websockets.serve(handler, "127.0.0.1", 0) as server:
        port = server.sockets[0].getsockname()[1]
        with pytest.raises(XenonFeedUnavailable):
            async with XenonWsClient(f"ws://127.0.0.1:{port}", status_timeout=0.3):
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
