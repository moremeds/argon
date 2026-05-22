"""In-memory latest-tick-per-ticker buffer for the WS consumer.

The consumer pushes ticks as they arrive; the writer drains periodically
(e.g., every 1s) and persists the snapshot in a single transaction.

Thread-safe via a threading.Lock — `add` and `drain` can be called from
different asyncio tasks (the writer uses asyncio.to_thread to run flush
on the default executor, so the buffer is touched from both the event
loop and a worker thread).

The buffer also tracks raw-feed volume since the last successful drain
(``received_count``). Tracking lives here, under the same lock that
guards ``_latest``, so the WS reader's ``note_received`` increment cannot
race with ``flush_once``'s read+reset (tribunal ISSUE-3).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping
from dataclasses import dataclass

from uw_scan.sources.massive_ws import WsTick


@dataclass(frozen=True)
class BufferSnapshot:
    """What ``TickBuffer.drain()`` returns: latest tick per ticker + the
    raw count of frames seen since the last drain. Coupled so reader-side
    increments and writer-side resets are atomic w.r.t. each other."""

    latest: Mapping[str, WsTick]
    received_count: int


class TickBuffer:
    """Keep only the latest tick (by quoted_at) per ticker."""

    def __init__(self) -> None:
        self._latest: dict[str, WsTick] = {}
        self._received_count: int = 0
        self._lock = threading.Lock()

    def add(self, tick: WsTick) -> None:
        with self._lock:
            existing = self._latest.get(tick.ticker)
            if existing is None or tick.quoted_at >= existing.quoted_at:
                self._latest[tick.ticker] = tick

    def add_if_newer(self, tick: WsTick) -> None:
        """Restore-path variant of ``add()``: STRICTLY newer wins.

        Used by ``WsDbWriter.flush_once``'s except branch (tribunal
        adversarial-2). When a failed flush merges its in-flight pending
        snapshot back into the buffer, any tick still in pending is by
        definition no newer than what arrived during the flush. With
        ``add``'s ``>=`` rule, an equal-timestamp restore would clobber
        a freshly-observed live tick with stale pending data; this
        variant preserves the existing entry on ties.
        """
        with self._lock:
            existing = self._latest.get(tick.ticker)
            if existing is None or tick.quoted_at > existing.quoted_at:
                self._latest[tick.ticker] = tick

    def note_received(self, count: int = 1) -> None:
        """Increment the raw-frame counter. Called by the WS reader BEFORE
        coalescing into ``_latest``; ``flush_once`` reads + resets via
        ``drain`` so the increment and reset can't race."""
        with self._lock:
            self._received_count += count

    def drain(self) -> BufferSnapshot:
        """Atomically return + clear the buffer and the received counter."""
        with self._lock:
            snapshot = BufferSnapshot(
                latest=self._latest, received_count=self._received_count
            )
            self._latest = {}
            self._received_count = 0
            return snapshot

    def __len__(self) -> int:
        with self._lock:
            return len(self._latest)
