"""In-memory latest-tick-per-ticker buffer for the WS consumer.

The consumer pushes ticks as they arrive; the writer drains periodically
(e.g., every 1s) and persists the snapshot in a single transaction.

Thread-safe via a threading.Lock — `add` and `drain` can be called from
different asyncio tasks (the writer uses asyncio.to_thread to run flush
on the default executor, so the buffer is touched from both the event
loop and a worker thread).
"""

from __future__ import annotations

import threading
from collections.abc import Mapping

from uw_scan.sources.massive_ws import WsTick


class TickBuffer:
    """Keep only the latest tick (by quoted_at) per ticker."""

    def __init__(self) -> None:
        self._latest: dict[str, WsTick] = {}
        self._lock = threading.Lock()

    def add(self, tick: WsTick) -> None:
        with self._lock:
            existing = self._latest.get(tick.ticker)
            if existing is None or tick.quoted_at >= existing.quoted_at:
                self._latest[tick.ticker] = tick

    def drain(self) -> Mapping[str, WsTick]:
        """Atomically return + clear the buffer."""
        with self._lock:
            snapshot = self._latest
            self._latest = {}
            return snapshot

    def __len__(self) -> int:
        with self._lock:
            return len(self._latest)
