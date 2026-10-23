"""SpotsBroadcaster fan-out and the SSE framing — no DB (the listener is stubbed)."""

from __future__ import annotations

import json
from datetime import datetime, timezone
from decimal import Decimal

import pytest

from uw_scan.api import live_spots
from uw_scan.api.live_spots import SpotsBroadcaster, sse_events

# TSLA's real 2026-10-21 / 2026-10-22 closes (livewire lake, fetched 2026-10-23).
T0 = datetime(2026, 10, 22, 20, 0, tzinfo=timezone.utc)
TSLA = ("TSLA", Decimal("386.47"), T0, "xenon_ws")
TSLA_MOVED = ("TSLA", Decimal("374.58"), T0, "xenon_ws")
SPY = ("SPY", None, None, None)


async def _no_listen(self) -> None:
    return None


@pytest.fixture
def broadcaster(monkeypatch) -> SpotsBroadcaster:
    monkeypatch.setattr(SpotsBroadcaster, "_listen", _no_listen)
    return SpotsBroadcaster("unused", lambda: [])


def _tickers(message: str) -> list[str]:
    return [s["ticker"] for s in json.loads(message)["spots"]]


@pytest.mark.asyncio
async def test_publish_sends_only_changed_rows(broadcaster):
    queue = broadcaster.subscribe()
    broadcaster.publish([TSLA, SPY])
    assert _tickers(queue.get_nowait()) == ["TSLA", "SPY"]  # first read: all new
    broadcaster.publish([TSLA, SPY])
    assert queue.empty()  # nothing changed, nothing sent
    broadcaster.publish([TSLA_MOVED, SPY])
    message = json.loads(queue.get_nowait())
    assert [s["ticker"] for s in message["spots"]] == ["TSLA"]
    assert Decimal(message["spots"][0]["spot"]) == Decimal("374.58")


@pytest.mark.asyncio
async def test_late_subscriber_gets_full_snapshot_first(broadcaster):
    broadcaster.subscribe()
    broadcaster.publish([TSLA, SPY])
    late = broadcaster.subscribe()
    assert _tickers(late.get_nowait()) == ["TSLA", "SPY"]


@pytest.mark.asyncio
async def test_full_queue_is_resynced_with_one_snapshot(broadcaster, monkeypatch):
    monkeypatch.setattr(live_spots, "QUEUE_MAX", 1)
    queue = broadcaster.subscribe()
    broadcaster.publish([TSLA])
    broadcaster.publish([TSLA_MOVED, SPY])  # queue full: drop backlog, resync
    assert queue.qsize() == 1
    message = json.loads(queue.get_nowait())
    assert [s["ticker"] for s in message["spots"]] == ["TSLA", "SPY"]
    assert Decimal(message["spots"][0]["spot"]) == Decimal("374.58")


@pytest.mark.asyncio
async def test_sse_frames_heartbeat_and_unsubscribe(broadcaster, monkeypatch):
    monkeypatch.setattr(live_spots, "HEARTBEAT_SECONDS", 0.01)
    events = sse_events(broadcaster)
    assert await anext(events) == "retry: 2000\n\n"
    # Idle stream: a named event the browser's watchdog can see.
    assert await anext(events) == "event: ping\ndata: 1\n\n"
    broadcaster.publish([TSLA])
    frame = await anext(events)
    assert frame.startswith("data: ") and frame.endswith("\n\n")
    assert _tickers(frame.removeprefix("data: ").strip()) == ["TSLA"]
    await events.aclose()
    assert not broadcaster._subs  # closed stream unsubscribes
