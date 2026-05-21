"""Integration tests for the WS consumer state mixin (Phase 1)."""

from __future__ import annotations

from datetime import datetime, timezone


def _utcnow():
    return datetime.now(timezone.utc)


def test_record_ws_heartbeat_persists(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_heartbeat(
        last_tick_at=ts,
        last_flush_at=ts,
        ticks_received_delta=10,
        ticks_flushed_delta=10,
    )
    repo._conn.commit()  # helpers don't self-commit — caller controls txn
    row = repo.get_ws_consumer_state()
    assert row is not None
    assert row.last_tick_at == ts
    assert row.ticks_received == 10
    assert row.ticks_flushed == 10


def test_ws_heartbeat_accumulates_counters(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts1, ts2 = _utcnow(), _utcnow()
    repo.record_ws_heartbeat(
        last_tick_at=ts1,
        last_flush_at=ts1,
        ticks_received_delta=5,
        ticks_flushed_delta=5,
    )
    repo._conn.commit()
    repo.record_ws_heartbeat(
        last_tick_at=ts2,
        last_flush_at=ts2,
        ticks_received_delta=7,
        ticks_flushed_delta=7,
    )
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.ticks_received == 12
    assert row.ticks_flushed == 12


def test_record_ws_connection_started(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_connection_started(ts)
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.connection_started_at == ts


def test_record_ws_error(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_error("connection closed: 1006", ts)
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.last_error == "connection closed: 1006"
    assert row.last_error_at == ts


def test_heartbeat_null_last_tick_preserves_existing(seeded_db_empty_cards):
    """COALESCE(last_tick_at, last_tick_at): passing None must not clobber a prior tick time."""
    repo = seeded_db_empty_cards
    ts = _utcnow()
    repo.record_ws_heartbeat(
        last_tick_at=ts,
        last_flush_at=ts,
        ticks_received_delta=1,
        ticks_flushed_delta=1,
    )
    repo._conn.commit()
    # Second flush with no new ticks: last_tick_at should remain ts.
    later = _utcnow()
    repo.record_ws_heartbeat(
        last_tick_at=None,
        last_flush_at=later,
        ticks_received_delta=0,
        ticks_flushed_delta=0,
    )
    repo._conn.commit()
    row = repo.get_ws_consumer_state()
    assert row.last_tick_at == ts
    assert row.last_flush_at == later
