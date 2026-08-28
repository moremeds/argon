"""Per-print earnings reaction history (spec §5-ii).

Standalone repository, not a `Repository` mixin — same rationale as
`earnings_calendar.py`: `repository.py` is closed to new query methods, and
this is its own domain.

A row here is a COMPLETE FACT: both the pre-print and post-print closes were
observed in `daily_ohlc`. There is no partial row and no NULL placeholder for
a pending print — `earnings_reactions_compute` (worker/jobs/earnings_reactions.py)
simply skips a print until both closes land, and the calendar row (migration
144) is what tells a reader the print is expected but not yet resolved.
`upsert_rows` is therefore `ON CONFLICT ... DO NOTHING`: a computed reaction
is a fact and is never silently recomputed. Recomputing (e.g. after an OHLC
correction) requires an explicit delete first.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg


class EarningsReactionsRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert-or-skip. Returns rows genuinely NEW (measured via
        `xmax = 0`, matching `EarningsCalendarRepository.upsert_rows`'
        honesty rule — a replay must report zero, not `len(rows)`)."""
        if not rows:
            return 0
        table = f"{self._schema}.earnings_reactions"
        sql = f"""
            INSERT INTO {table}
                        (ticker, report_date, session, close_before_date,
                         close_before, close_after_date, close_after, pct_move)
                 VALUES (%(ticker)s, %(report_date)s, %(session)s,
                         %(close_before_date)s, %(close_before)s,
                         %(close_after_date)s, %(close_after)s, %(pct_move)s)
            ON CONFLICT (ticker, report_date) DO NOTHING
              RETURNING (xmax = 0) AS inserted
        """
        inserted = 0
        with self.conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, {**row, "ticker": row["ticker"].upper()})
                fetched = cur.fetchone()
                if fetched is not None and fetched[0]:
                    inserted += 1
        self.conn.commit()
        return inserted

    def last_reactions(self, ticker: str, n: int = 4) -> list[dict[str, Any]]:
        """Newest-first, most recent `n` reactions for one ticker."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, report_date, session, close_before_date,
                           close_before, close_after_date, close_after, pct_move,
                           computed_at
                      FROM {self._schema}.earnings_reactions
                     WHERE ticker = %s
                     ORDER BY report_date DESC
                     LIMIT %s""",
                (ticker.upper(), n),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def reactions_for(self, tickers: Sequence[str]) -> dict[str, list[dict[str, Any]]]:
        """All reactions for the given tickers, grouped by ticker, newest-first
        within each ticker's list."""
        out: dict[str, list[dict[str, Any]]] = {t.upper(): [] for t in tickers}
        if not tickers:
            return out
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, report_date, session, close_before_date,
                           close_before, close_after_date, close_after, pct_move,
                           computed_at
                      FROM {self._schema}.earnings_reactions
                     WHERE ticker = ANY(%s)
                     ORDER BY ticker, report_date DESC""",
                ([t.upper() for t in tickers],),
            )
            cols = [d.name for d in cur.description]
            for r in cur.fetchall():
                row = dict(zip(cols, r))
                out.setdefault(row["ticker"], []).append(row)
        return out
