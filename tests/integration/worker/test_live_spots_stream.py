"""WS writer flush → NOTIFY → API listener → stream queue, against a real Postgres."""

from __future__ import annotations

import asyncio
import json
from datetime import datetime, timezone
from decimal import Decimal

import psycopg
import pytest

from uw_scan.api.live_spots import SpotsBroadcaster
from uw_scan.sources.massive_ws import WsTick
from uw_scan.storage.repository import Repository
from uw_scan.worker.ws_db_writer import WsDbWriter
from uw_scan.worker.ws_tick_buffer import TickBuffer

pytestmark = pytest.mark.integration


@pytest.mark.asyncio
async def test_writer_flush_reaches_stream_subscriber(
    seeded_db_with_cards, _migrated_settings
):
    repo = seeded_db_with_cards
    repo._conn.autocommit = True  # production: transaction() issues BEGIN/COMMIT
    settings = _migrated_settings

    def read_spots():
        with psycopg.connect(settings.db_dsn()) as conn:
            return Repository(conn, schema=settings.db_schema).list_watchlist_spots()

    broadcaster = SpotsBroadcaster(settings.db_dsn(), read_spots)
    queue = broadcaster.subscribe()
    try:
        # The listener's first read publishes the whole watchlist.
        first = json.loads(await asyncio.wait_for(queue.get(), 10))
        assert "TSLA" in {s["ticker"] for s in first["spots"]}

        # TSLA's real 2026-10-22 close (livewire lake, fetched 2026-10-23).
        buffer = TickBuffer()
        buffer.add(
            WsTick(
                "TSLA",
                Decimal("374.58"),
                datetime.now(timezone.utc),
                "X",
                source="xenon_ws",
            )
        )
        writer = WsDbWriter(repo=repo, buffer=buffer, source_tag="xenon_ws")
        assert await asyncio.to_thread(writer.flush_once) == 1

        pushed = json.loads(await asyncio.wait_for(queue.get(), 5))
        assert [s["ticker"] for s in pushed["spots"]] == ["TSLA"]  # only the change
        assert Decimal(pushed["spots"][0]["spot"]) == Decimal("374.58")
        assert pushed["spots"][0]["spot_source"] == "xenon_ws"
    finally:
        broadcaster._task.cancel()
