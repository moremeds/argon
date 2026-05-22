"""Integration tests for WsDbWriter (Phase 3, Task 3.2-3.3)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from decimal import Decimal

import pytest

from uw_scan.sources.massive_ws import WsTick
from uw_scan.worker.ws_db_writer import WsDbWriter
from uw_scan.worker.ws_tick_buffer import TickBuffer


def test_writer_flushes_buffer_to_db(seeded_db_with_cards):
    """seeded_db_with_cards seeds one TSLA card. We tick TSLA (real card)
    + INTC (no card row) — INTC should land in intraday_quote but not in
    watchlist_card (silently skipped, that's the contract)."""
    repo = seeded_db_with_cards
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")

    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    buf.add(WsTick("INTC", Decimal("32.10"), ts, "A"))

    n = writer.flush_once()
    assert n == 2

    q_tsla = repo.get_intraday_quote("TSLA")
    assert q_tsla.price == Decimal("450.00")
    q_intc = repo.get_intraday_quote("INTC")
    # FK was dropped in migration 052 so orphan tickers persist (A3).
    assert q_intc.price == Decimal("32.10")
    c_tsla = repo.get_watchlist_card("TSLA")
    assert c_tsla.spot == Decimal("450.00")
    assert c_tsla.spot_source == "massive.com_ws"
    assert repo.get_watchlist_card("INTC") is None  # no card was created

    state = repo.get_ws_consumer_state()
    assert state.ticks_flushed == 2


def test_writer_empty_buffer_is_noop(seeded_db_with_cards):
    repo = seeded_db_with_cards
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    assert writer.flush_once() == 0


def test_writer_atomicity_rolls_back_on_failure(seeded_db_with_cards, monkeypatch):
    """If bulk_upsert_watchlist_card_quotes raises, intraday_quote also rolls back.

    Mirrors production behavior: the writer expects an autocommit conn so
    ``with conn.transaction()`` issues explicit BEGIN/COMMIT/ROLLBACK around
    the batch (verified against psycopg3 docs:
    https://www.psycopg.org/psycopg3/docs/basic/transactions.html —
    "If you want to use an autocommit connection but still wrap selected
    groups of commands inside an atomic transaction, you can use a
    transaction() context. When entered, BEGIN is executed and a transaction
    is started, and COMMIT is executed at the end of the block.")

    Also verifies A2: pending batch is merged back into the buffer on failure.
    """
    repo = seeded_db_with_cards
    repo._conn.autocommit = True  # mirror production setup
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))

    def boom(*_a, **_k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(repo, "bulk_upsert_watchlist_card_quotes", boom)
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    with pytest.raises(RuntimeError):
        writer.flush_once()

    # intraday_quote should NOT have TSLA — the with conn.transaction() block
    # issued ROLLBACK when boom raised.
    assert repo.get_intraday_quote("TSLA") is None
    # A2: pending merged back to live buffer so next flush retries.
    assert len(buf) == 1


def test_writer_persists_intraday_returns(seeded_db_with_cards):
    """R9: flush_once must update ret_1d / ret_1w / ret_30d so the dashboard
    cards stay in sync with the intraday spot. Without this, returns would
    be frozen at full_scan time and drift from the WS spot."""
    repo = seeded_db_with_cards
    # Backfill 30 days of TSLA daily OHLC at close=440 so a 450 tick yields
    # ret_1d ≈ +2.27%.
    today = datetime.now(timezone.utc).date()
    for i in range(30):
        d = today - timedelta(days=30 - i)
        if d.weekday() >= 5:
            continue  # OHLC stores weekday-only
        repo.upsert_daily_ohlc(
            ticker="TSLA",
            date=d,
            open=Decimal("440"),
            high=Decimal("442"),
            low=Decimal("438"),
            close=Decimal("440"),
            volume=10_000_000,
            source="massive.com",
        )
    repo._conn.commit()

    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    ts = datetime.now(timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    writer.flush_once()

    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("450.00")
    # (450 - 440) / 440 ≈ 0.02272727...
    assert card.ret_1d is not None
    assert abs(float(card.ret_1d) - 0.02273) < 0.001


def test_writer_pending_drained_on_success(seeded_db_with_cards):
    """After a successful flush, internal _pending state must be empty
    so the next flush_once starts fresh."""
    repo = seeded_db_with_cards
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    writer.flush_once()
    assert writer._pending == {}

    # Second flush with new tick: no double-write of TSLA at the OLD ts.
    ts2 = datetime(2026, 5, 21, 14, 0, 5, tzinfo=timezone.utc)
    buf.add(WsTick("TSLA", Decimal("451.00"), ts2, "A"))
    writer.flush_once()
    card = repo.get_watchlist_card("TSLA")
    assert card.spot == Decimal("451.00")
    assert card.spot_quoted_at == ts2


def test_writer_received_counter_resets_per_flush(seeded_db_with_cards):
    """A12: ticks_received counts raw frames since the last successful flush."""
    repo = seeded_db_with_cards
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)

    # 5 raw frames, but coalesce to 1 unique ticker.
    for _ in range(5):
        writer.note_received(1)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    writer.flush_once()
    state = repo.get_ws_consumer_state()
    assert state.ticks_received == 5
    assert state.ticks_flushed == 1

    # Counter must reset after a successful flush.
    for _ in range(3):
        writer.note_received(1)
    buf.add(WsTick("TSLA", Decimal("451.00"), ts, "A"))
    writer.flush_once()
    state = repo.get_ws_consumer_state()
    assert state.ticks_received == 5 + 3
    assert state.ticks_flushed == 2


def test_writer_received_count_restored_on_history_failure(
    seeded_db_with_cards, monkeypatch
):
    """ISSUE-3 second-pass: when an exception fires BETWEEN drain() and
    the transaction (e.g., _history_for's list_daily_ohlc DB call hits
    a transient failure), the received_delta must still be restored.
    Without the extended restore guard, drain()'s eager reset would
    silently zero out the raw-feed count even though the ticks survive
    via _pending and are retried on the next flush.
    """
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")

    # 6 raw frames + 1 coalesced tick. First flush fails INSIDE _history_for.
    for _ in range(6):
        writer.note_received(1)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))

    def boom_history(*_a, **_k):
        raise RuntimeError("simulated OHLC DB failure")

    monkeypatch.setattr(repo, "list_daily_ohlc", boom_history)
    with pytest.raises(RuntimeError):
        writer.flush_once()

    # The buffer must once again hold the tick + the raw-feed count.
    assert len(buf) == 1, "tick should be merged back to buffer"

    # On the next successful flush, ticks_received must reflect ALL 6
    # raw frames — not 0 (which would be the bug).
    monkeypatch.undo()
    writer.flush_once()
    state = repo.get_ws_consumer_state()
    assert state.ticks_received == 6
    assert state.ticks_flushed == 1


def test_writer_received_count_restored_on_flush_failure(
    seeded_db_with_cards, monkeypatch
):
    """ISSUE-3 regression: when a flush fails, the raw-feed counter must
    be restored along with the tick payload — losing it under-reports
    ``ticks_received`` even though the ticks themselves are retried."""
    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    buf = TickBuffer()
    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")

    # 4 raw frames + 1 coalesced tick. First flush fails.
    for _ in range(4):
        writer.note_received(1)
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))

    def boom(*_a, **_k):
        raise RuntimeError("simulated DB failure")

    monkeypatch.setattr(repo, "bulk_upsert_intraday_quotes", boom)
    with pytest.raises(RuntimeError):
        writer.flush_once()

    monkeypatch.undo()
    # Tick AND received_delta both still queued.
    writer.flush_once()
    state = repo.get_ws_consumer_state()
    # All 4 raw frames must be reported (not 0).
    assert state.ticks_received == 4
    assert state.ticks_flushed == 1


def test_writer_lock_serializes_concurrent_flush(seeded_db_with_cards):
    """ISSUE-2 regression: two concurrent ``flush_once`` calls (e.g., a
    still-running periodic flush + the finally-clause flush after cancel)
    must not race on the shared psycopg connection or on ``_pending``.

    Without the writer-level lock, two threads hitting ``conn.transaction()``
    on the same connection raises 'another command is already in progress'
    in psycopg3. With the lock the two flushes run in sequence.
    """
    import threading

    repo = seeded_db_with_cards
    repo._conn.autocommit = True
    buf = TickBuffer()
    writer = WsDbWriter(repo=repo, buffer=buf, source_tag="massive.com_ws")

    ts = datetime(2026, 5, 21, 14, 0, tzinfo=timezone.utc)
    # Two ticks so both threads see something to flush.
    buf.add(WsTick("TSLA", Decimal("450.00"), ts, "A"))
    buf.add(WsTick("AAPL", Decimal("189.10"), ts, "A"))

    errors: list[BaseException] = []
    barrier = threading.Barrier(2)

    def flush_at_barrier():
        try:
            barrier.wait(timeout=2.0)
            writer.flush_once()
        except BaseException as exc:  # noqa: BLE001
            errors.append(exc)

    t1 = threading.Thread(target=flush_at_barrier)
    t2 = threading.Thread(target=flush_at_barrier)
    t1.start()
    t2.start()
    t1.join(timeout=5.0)
    t2.join(timeout=5.0)

    assert not errors, f"concurrent flush raised: {errors!r}"
    # Both ticks must have landed.
    assert repo.get_intraday_quote("TSLA").price == Decimal("450.00")
    assert repo.get_intraday_quote("AAPL").price == Decimal("189.10")
