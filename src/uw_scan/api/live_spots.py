"""Push live watchlist spots to browsers over Server-Sent Events.

The WS writer NOTIFYs ``SPOTS_CHANNEL`` inside each flush transaction. One
LISTEN connection per API process wakes on every commit, re-reads the spots
projection, and fans only the changed rows out to every open stream. Latency
is the writer's flush interval plus one ~10 ms read, instead of a 2.5 s poll.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator, Callable
from datetime import datetime
from decimal import Decimal

import psycopg

from uw_scan.models.watchlist import WatchlistSpot, WatchlistSpotsResponse
from uw_scan.storage.watchlist import SPOTS_CHANNEL

logger = logging.getLogger(__name__)

SpotRow = tuple[str, Decimal | None, datetime | None, str | None]

# A real event, not an SSE comment: the browser can't see comments, and it needs
# a pulse to notice a dead stream — when the API restarts, the Next proxy can
# leave the browser's half open and silent (LiveSpotsProvider's watchdog).
HEARTBEAT_SECONDS = 2.0
RECONNECT_SECONDS = 1.0
QUEUE_MAX = 64  # a stream this far behind is resynced with one full snapshot


def spots_response(rows: list[SpotRow]) -> WatchlistSpotsResponse:
    return WatchlistSpotsResponse(
        spots=[
            WatchlistSpot(
                ticker=ticker, spot=spot, spot_quoted_at=quoted_at, spot_source=source
            )
            for (ticker, spot, quoted_at, source) in rows
        ]
    )


def encode(rows: list[SpotRow]) -> str:
    return spots_response(rows).model_dump_json()


class SpotsBroadcaster:
    def __init__(self, dsn: str, read_spots: Callable[[], list[SpotRow]]) -> None:
        self._dsn = dsn
        self._read_spots = read_spots
        self._last: dict[str, SpotRow] = {}
        self._subs: set[asyncio.Queue[str]] = set()
        self._task: asyncio.Task[None] | None = None

    def subscribe(self) -> asyncio.Queue[str]:
        """New stream: queue primed with the full snapshot when one is known
        (otherwise the listener's first read publishes everything)."""
        queue: asyncio.Queue[str] = asyncio.Queue(maxsize=QUEUE_MAX)
        if self._last:
            queue.put_nowait(encode(list(self._last.values())))
        self._subs.add(queue)
        # ponytail: the listener runs for the process lifetime once started —
        # one idle connection; stop it on last unsubscribe if that ever matters.
        if self._task is None or self._task.done():
            self._task = asyncio.create_task(self._listen())
        return queue

    def unsubscribe(self, queue: asyncio.Queue[str]) -> None:
        self._subs.discard(queue)

    def publish(self, rows: list[SpotRow]) -> None:
        changed = [row for row in rows if self._last.get(row[0]) != row]
        self._last = {row[0]: row for row in rows}
        if not changed:
            return
        message = encode(changed)
        for queue in self._subs:
            try:
                queue.put_nowait(message)
            except asyncio.QueueFull as exc:
                logger.info("live_spots stream fell behind, resyncing: %s", repr(exc))
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(encode(list(self._last.values())))

    async def _refresh(self) -> None:
        self.publish(await asyncio.to_thread(self._read_spots))

    async def _listen(self) -> None:
        while True:
            try:
                async with await psycopg.AsyncConnection.connect(
                    self._dsn, autocommit=True
                ) as conn:
                    await conn.execute(f"LISTEN {SPOTS_CHANNEL}")
                    # Read once per (re)connect: covers the first subscriber
                    # off-hours (no flush to wake us) and any NOTIFY missed
                    # while the connection was down.
                    await self._refresh()
                    async for _ in conn.notifies():
                        await self._refresh()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                logger.warning("live_spots listener failed: %s", repr(exc))
                await asyncio.sleep(RECONNECT_SECONDS)


async def sse_events(broadcaster: SpotsBroadcaster) -> AsyncIterator[str]:
    queue = broadcaster.subscribe()
    try:
        yield "retry: 2000\n\n"
        while True:
            try:
                message = await asyncio.wait_for(queue.get(), HEARTBEAT_SECONDS)
            except TimeoutError as exc:
                logger.debug("live_spots heartbeat: %s", repr(exc))
                yield "event: ping\ndata: 1\n\n"
                continue
            yield f"data: {message}\n\n"
    finally:
        broadcaster.unsubscribe(queue)
