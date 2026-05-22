"""Drain a TickBuffer and persist as a single atomic batch.

Writes happen under one psycopg transaction wrapping:
  1. bulk_upsert_intraday_quotes (canonical source of truth)
  2. bulk_upsert_watchlist_card_quotes (denormalized for fast dashboard reads,
     incl. ret_1d / ret_1w / ret_30d computed against the latest tick)
  3. record_ws_heartbeat (operator visibility)

A2 (adversarial fix): drained ticks are held in ``_pending`` and only cleared
after a successful commit. On failure the pending batch is merged back into
the live buffer so the next flush retries — ticks are never lost to a
transient DB error.

A6 (adversarial fix): the OHLC cache key includes the ET market-session date
so a new trading day naturally invalidates stale closes. Avoids a memory
leak (cache grew forever) AND the wrong-day staleness that
``invalidate_ohlc_cache()`` was supposed to fix but had no caller.

A12 (adversarial fix): ticks_received counts raw frames (per ``note_received``)
while ticks_flushed counts post-coalesce commits. Both surface in
``/api/health`` so ops can see feed volume independent of buffer rate.
"""

from __future__ import annotations

import logging
import threading
from datetime import date, datetime, timedelta, timezone

from uw_scan.cards.returns import compute_returns
from uw_scan.sources.massive_ws import WsTick
from uw_scan.storage.repository import Repository
from uw_scan.storage.rows import DailyOhlcRow
from uw_scan.worker.market_session import current_market_date
from uw_scan.worker.ws_tick_buffer import TickBuffer

logger = logging.getLogger(__name__)


class WsDbWriter:
    def __init__(
        self,
        *,
        repo: Repository,
        buffer: TickBuffer,
        source_tag: str = "massive.com_ws",
    ) -> None:
        self._repo = repo
        self._buffer = buffer
        self._source_tag = source_tag
        # Cache key is (ticker, market_date) so a new trading day naturally
        # invalidates yesterday's closes.
        self._ohlc_cache: dict[tuple[str, date], list[DailyOhlcRow]] = {}
        # A2: held until commit succeeds; merged back into buffer on failure.
        self._pending: dict[str, WsTick] = {}
        # Serializes flush_once across the two threads that can call it
        # (tribunal ISSUE-2): asyncio.to_thread inside _flush_loop cannot
        # cancel its executor thread, so the finally-clause flush in
        # run_consumer_once can fire while a periodic flush is still in
        # flight — two threads on the same psycopg connection raise
        # "another command is already in progress". The lock also gates
        # the received-counter read+reset against the WS reader thread
        # (ISSUE-3), which acquires it via TickBuffer.add through
        # note_received.
        self._flush_lock = threading.Lock()

    def note_received(self, count: int = 1) -> None:
        """Called from the WS reader on every tick BEFORE coalescing.

        Thin pass-through to ``TickBuffer.note_received`` — the counter
        now lives on the buffer so increments and the drain-time reset
        share a lock (tribunal ISSUE-3). Used by
        ``record_ws_heartbeat(ticks_received_delta=...)`` to surface
        true feed volume separately from the coalesced flush count.
        """
        self._buffer.note_received(count)

    def _market_session_date(self, now: datetime | None = None) -> date:
        """Cache key for OHLC. Falls back to the most recent weekday outside RTH."""
        now = now or datetime.now(timezone.utc)
        md = current_market_date(now)
        if md is not None:
            return md
        d = now.date()
        while d.weekday() >= 5:
            d -= timedelta(days=1)
        return d

    def _history_for(self, ticker: str) -> list[DailyOhlcRow]:
        market_date = self._market_session_date()
        key = (ticker, market_date)
        if key not in self._ohlc_cache:
            self._ohlc_cache[key] = self._repo.list_daily_ohlc(ticker, limit=40)
            # Bound memory: drop entries from earlier session dates.
            self._ohlc_cache = {
                k: v for k, v in self._ohlc_cache.items() if k[1] == market_date
            }
        return self._ohlc_cache[key]

    def flush_once(self) -> int:
        """Drain + flush. Returns number of tickers written.

        On exception: rolls back the transaction AND merges the in-flight
        snapshot back into the live buffer so the next flush retries.

        Serialized via ``self._flush_lock`` (tribunal ISSUE-2): the
        executor thread holding an in-flight flush at TaskGroup-cancel
        time cannot be cancelled — Python's ``asyncio.to_thread`` only
        cancels the awaiting coroutine, not the thread. The
        ``run_consumer_once`` finally-clause then fires a second
        ``flush_once`` while the first is still touching the psycopg
        connection. Acquiring the lock serializes the two so they share
        the connection in sequence rather than racing on it.

        Restore guard: ``drain()`` eagerly resets the raw-feed counter
        (tribunal ISSUE-3). EVERY exception path after the drain — not
        just the DB transaction — must restore the count + ticks back
        into the buffer; otherwise an exception from ``_history_for``
        (a DB call that loads OHLC) or ``compute_returns`` would leave
        the counter zero'd and under-report feed volume on the next
        successful flush (second-pass Codex review).
        """
        with self._flush_lock:
            # Drain into pending; merge with any pending from a prior
            # failed flush. drain() returns BOTH the snapshot AND the
            # raw-feed count so increments-since-last-drain can't be
            # erased by a concurrent reset (tribunal ISSUE-3).
            drained = self._buffer.drain()
            snapshot = dict(drained.latest)
            received_delta = drained.received_count
            if self._pending:
                for ticker, tick in self._pending.items():
                    existing = snapshot.get(ticker)
                    if existing is None or tick.quoted_at > existing.quoted_at:
                        snapshot[ticker] = tick
                self._pending = {}
            if not snapshot and received_delta == 0:
                return 0
            self._pending = snapshot  # held until commit succeeds

            n = 0
            try:
                quote_rows: list[tuple] = []
                card_rows: list[tuple] = []
                latest_quoted_at: datetime | None = None
                for tick in snapshot.values():
                    quote_rows.append(
                        (tick.ticker, tick.price, tick.quoted_at, self._source_tag)
                    )
                    # _history_for is a DB read — can raise. Must be inside
                    # the guarded block so the restore path fires on its
                    # failures, not just on the txn's failures.
                    history = self._history_for(tick.ticker)
                    returns = compute_returns(history, tick.price)
                    card_rows.append(
                        (
                            tick.ticker,
                            tick.price,
                            tick.quoted_at,
                            self._source_tag,
                            returns.ret_1d,
                            returns.ret_1w,
                            returns.ret_30d,
                        )
                    )
                    if latest_quoted_at is None or tick.quoted_at > latest_quoted_at:
                        latest_quoted_at = tick.quoted_at

                flush_at = datetime.now(timezone.utc)
                n = len(quote_rows)
                with self._repo.conn.transaction():
                    self._repo.bulk_upsert_intraday_quotes(quote_rows)
                    self._repo.bulk_upsert_watchlist_card_quotes(card_rows)
                    self._repo.record_ws_heartbeat(
                        last_tick_at=latest_quoted_at,
                        last_flush_at=flush_at,
                        ticks_received_delta=received_delta,
                        ticks_flushed_delta=n,
                    )
                # Commit succeeded — release pending.
                self._pending = {}
            except Exception:
                held = len(self._pending)
                logger.exception(
                    "ws_db_writer flush failed; %d ticks held for retry", held
                )
                # Merge pending back into the live buffer so next flush
                # retries. ``add_if_newer`` (tribunal adversarial-2)
                # avoids clobbering a same-instant tick that arrived in
                # the live buffer while this flush was in flight — the
                # pending tick is by definition no fresher than the
                # live one. The received_delta count is also restored
                # so the next successful flush reports true raw volume.
                for tick in self._pending.values():
                    self._buffer.add_if_newer(tick)
                self._pending = {}
                if received_delta > 0:
                    self._buffer.note_received(received_delta)
                raise
            logger.debug("ws_db_writer flushed %d ticks", n)
            return n
