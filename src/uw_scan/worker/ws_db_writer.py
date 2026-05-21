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
        # A12: raw feed volume since last successful flush.
        self._ticks_seen_since_last_flush: int = 0

    def note_received(self, count: int = 1) -> None:
        """Called from the WS reader on every tick BEFORE coalescing.

        Used by ``record_ws_heartbeat(ticks_received_delta=...)`` to surface
        true feed volume separately from the coalesced flush count.
        """
        self._ticks_seen_since_last_flush += count

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
        """
        # Drain into pending; merge with any pending from a prior failed flush.
        snapshot = dict(self._buffer.drain())
        if self._pending:
            for ticker, tick in self._pending.items():
                existing = snapshot.get(ticker)
                if existing is None or tick.quoted_at > existing.quoted_at:
                    snapshot[ticker] = tick
            self._pending = {}
        if not snapshot:
            return 0
        self._pending = snapshot  # held until commit succeeds

        quote_rows: list[tuple] = []
        card_rows: list[tuple] = []
        latest_quoted_at: datetime | None = None
        for tick in snapshot.values():
            quote_rows.append(
                (tick.ticker, tick.price, tick.quoted_at, self._source_tag)
            )
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
        received_delta = self._ticks_seen_since_last_flush
        try:
            with self._repo._conn.transaction():
                self._repo.bulk_upsert_intraday_quotes(quote_rows)
                self._repo.bulk_upsert_watchlist_card_quotes(card_rows)
                self._repo.record_ws_heartbeat(
                    last_tick_at=latest_quoted_at,
                    last_flush_at=flush_at,
                    ticks_received_delta=received_delta,
                    ticks_flushed_delta=n,
                )
            # Commit succeeded — release pending and reset received counter.
            self._pending = {}
            self._ticks_seen_since_last_flush = 0
        except Exception:
            logger.exception("ws_db_writer flush failed; %d ticks held for retry", n)
            # Merge pending back into the live buffer so next flush retries.
            for tick in self._pending.values():
                self._buffer.add(tick)
            self._pending = {}
            raise
        logger.debug("ws_db_writer flushed %d ticks", n)
        return n
