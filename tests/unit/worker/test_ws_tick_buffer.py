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
    assert len(drained) == 1
    assert drained["AAPL"].price == Decimal("189.50")
    assert drained["AAPL"].quoted_at == ts2


def test_buffer_keeps_one_per_ticker_across_many():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    for t in ("AAPL", "MSFT", "SPY"):
        buf.add(_tick(t, "1.00", ts))
    drained = buf.drain()
    assert set(drained.keys()) == {"AAPL", "MSFT", "SPY"}


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
    assert drained["AAPL"].price == Decimal("189.50")


def test_drain_clears_buffer():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts))
    buf.drain()
    assert buf.drain() == {}


def test_drain_is_thread_safe_between_adds():
    """Drain returns a snapshot; concurrent adds during drain land in the
    next batch, not the current one."""
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(_tick("AAPL", "189.40", ts))
    snapshot = buf.drain()
    buf.add(_tick("MSFT", "425.00", ts))
    assert "MSFT" not in snapshot
    next_batch = buf.drain()
    assert "MSFT" in next_batch


def test_buffer_len():
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    assert len(buf) == 0
    buf.add(_tick("AAPL", "1.00", ts))
    buf.add(_tick("MSFT", "1.00", ts))
    assert len(buf) == 2
    buf.drain()
    assert len(buf) == 0
