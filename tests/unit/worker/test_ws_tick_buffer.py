"""Unit tests for TickBuffer (Phase 3, Task 3.1)."""

from __future__ import annotations

from datetime import datetime, timezone
from decimal import Decimal

from uw_scan.sources.massive_ws import WsTick
from uw_scan.worker.ws_tick_buffer import TickBuffer


def _tick(ticker: str, price: str, ts: datetime) -> WsTick:
    return WsTick(ticker=ticker, price=Decimal(price), quoted_at=ts, channel="A")


def test_buffer_keeps_latest_per_ticker():
    buf = TickBuffer()
    ts1 = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 0, 1, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts1))
    buf.add(_tick("AAPL", "189.50", ts2))
    drained = buf.drain()
    assert len(drained.latest) == 1
    assert drained.latest["AAPL"].price == Decimal("189.50")
    assert drained.latest["AAPL"].quoted_at == ts2


def test_buffer_keeps_one_per_ticker_across_many():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    for t in ("AAPL", "MSFT", "SPY"):
        buf.add(_tick(t, "1.00", ts))
    drained = buf.drain()
    assert set(drained.latest.keys()) == {"AAPL", "MSFT", "SPY"}


def test_buffer_does_not_regress_on_out_of_order():
    """If a later wall-clock tick has an EARLIER quoted_at (shouldn't normally
    happen but can during reconnects), we keep the one with the LATER
    quoted_at — that's the more recent observation."""
    buf = TickBuffer()
    ts1 = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 0, 5, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.50", ts2))  # newer arrives first
    buf.add(_tick("AAPL", "189.40", ts1))  # older arrives second
    drained = buf.drain()
    assert drained.latest["AAPL"].price == Decimal("189.50")


def test_drain_clears_buffer():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts))
    buf.drain()
    second = buf.drain()
    assert second.latest == {}
    assert second.received_count == 0


def test_drain_is_thread_safe_between_adds():
    """Drain returns a snapshot; concurrent adds during drain land in the
    next batch, not the current one."""
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts))
    snapshot = buf.drain()
    buf.add(_tick("MSFT", "425.00", ts))
    assert "MSFT" not in snapshot.latest
    next_batch = buf.drain()
    assert "MSFT" in next_batch.latest


def test_buffer_len():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    assert len(buf) == 0
    buf.add(_tick("AAPL", "1.00", ts))
    buf.add(_tick("MSFT", "1.00", ts))
    assert len(buf) == 2
    buf.drain()
    assert len(buf) == 0


def test_note_received_increments_and_drain_resets():
    """ISSUE-3 regression: received_count lives on the buffer so the read
    + reset is atomic w.r.t. concurrent note_received() calls."""
    buf = TickBuffer()
    buf.note_received(3)
    buf.note_received(2)
    drained = buf.drain()
    assert drained.received_count == 5
    # After drain, a new drain must see zero.
    assert buf.drain().received_count == 0


def test_note_received_survives_empty_drain():
    """If the buffer has zero coalesced ticks but received raw frames
    (only possible in an edge mode, e.g., a control frame counted as
    received), drain still surfaces the count so heartbeat reflects it."""
    buf = TickBuffer()
    buf.note_received(7)
    drained = buf.drain()
    assert drained.latest == {}
    assert drained.received_count == 7


def test_add_if_newer_keeps_existing_on_equal_timestamp():
    """Adversarial-2 regression: ``add_if_newer`` is the restore-path
    variant — equal-timestamp ties keep the EXISTING (live) tick because
    the pending tick that came back via flush_once's except branch is
    by definition no fresher than what arrived during the flush.

    Without strict ``>``, a same-instant pending replay would clobber
    a live correction.
    """
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    # Live buffer has the corrected value.
    buf.add(_tick("AAPL", "101.00", ts))
    # Restore-path replays the older pending value at the same ts.
    buf.add_if_newer(_tick("AAPL", "100.00", ts))
    drained = buf.drain()
    assert drained.latest["AAPL"].price == Decimal("101.00"), (
        "pending replay should NOT overwrite a same-instant live tick"
    )


def test_add_if_newer_writes_when_buffer_empty():
    """The strict-newer variant still writes when the slot is empty."""
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    buf.add_if_newer(_tick("AAPL", "100.00", ts))
    drained = buf.drain()
    assert drained.latest["AAPL"].price == Decimal("100.00")


def test_add_if_newer_overwrites_strictly_older():
    """Strictly older existing -> newer pending wins (rare but valid:
    a restore-path replay of a tick that arrived during a flush that
    came in OUT OF ORDER and was dropped by buf.add's >= guard)."""
    buf = TickBuffer()
    ts1 = datetime(2026, 5, 21, 14, 0, 0, tzinfo=timezone.utc)
    ts2 = datetime(2026, 5, 21, 14, 0, 1, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "100.00", ts1))
    buf.add_if_newer(_tick("AAPL", "101.00", ts2))
    drained = buf.drain()
    assert drained.latest["AAPL"].price == Decimal("101.00")


def test_concurrent_note_received_no_lost_updates():
    """ISSUE-3 regression: under thread contention, the running sum of
    note_received() calls must equal the count drain() reports.

    Without the per-buffer lock, the read-in-flush_once / reset-in-flush_once
    pattern could erase increments. With the lock, all note_received calls
    serialize against drain so the sum is exact.
    """
    import threading

    buf = TickBuffer()
    barrier = threading.Barrier(8)

    def worker():
        barrier.wait()
        for _ in range(1000):
            buf.note_received(1)

    threads = [threading.Thread(target=worker) for _ in range(8)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    drained = buf.drain()
    assert drained.received_count == 8 * 1000
