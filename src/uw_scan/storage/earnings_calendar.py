"""Durable earnings calendar (spec §5-i). Forward-accruing; insert-or-touch.

Standalone repository, not a `Repository` mixin — `repository.py` is closed to
new query methods (root CLAUDE.md module-size rule), and this is its own
domain: nothing on the shared `Repository` instance needs these methods today.
Matches the shape of `sec_filing_index.py` / `company_sector.py`.

WHY COALESCE ON `session` AND NOT A PLAIN OVERWRITE
----------------------------------------------------
A row can be discovered two ways: the UW classified calendar (carries a real
`session`) or the statement-obs fallback for the ~2% of names UW reports as
`report_time: "unknown"` (carries `session=None`). Either can arrive first.
`ON CONFLICT ... SET session = COALESCE(existing.session, EXCLUDED.session)`
makes the outcome order-independent: a NULL never clobbers a known value, and
a later-arriving known value fills a NULL. Leaving a column out of the SET
list entirely makes it write-once — that exact bug already cost this repo a
permanently discarded filing date (see the fundamental-ingest CLAUDE.md
entry) and is the reason this table exists at all.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg


class EarningsCalendarRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert-or-touch. Returns rows genuinely NEW (measured via `xmax = 0`,
        not assumed from `len(rows)` — a replay must report zero, honestly)."""
        if not rows:
            return 0
        table = f"{self._schema}.earnings_calendar"
        sql = f"""
            INSERT INTO {table}
                        (ticker, report_date, session, source)
                 VALUES (%(ticker)s, %(report_date)s, %(session)s, %(source)s)
            ON CONFLICT (ticker, report_date) DO UPDATE SET
                 -- late-known session fills in; a NULL never clobbers a value
                 session      = COALESCE({table}.session, EXCLUDED.session),
                 source       = CASE WHEN {table}.session IS NULL
                                      AND EXCLUDED.session IS NOT NULL
                                     THEN EXCLUDED.source
                                     ELSE {table}.source END,
                 last_seen_at = now()
              RETURNING (xmax = 0) AS inserted
        """
        inserted = 0
        with self.conn.cursor() as cur:
            for row in rows:
                cur.execute(sql, {**row, "ticker": row["ticker"].upper()})
                if cur.fetchone()[0]:
                    inserted += 1
        self.conn.commit()
        return inserted

    def next_prints(
        self, *, on_or_after: date, tickers: Sequence[str] | None = None
    ) -> list[dict[str, Any]]:
        sql = f"""SELECT ticker, report_date, session, source
                    FROM {self._schema}.earnings_calendar
                   WHERE report_date >= %s"""
        params: list[Any] = [on_or_after]
        if tickers is not None:
            sql += " AND ticker = ANY(%s)"
            params.append([t.upper() for t in tickers])
        sql += " ORDER BY report_date, ticker"
        with self.conn.cursor() as cur:
            cur.execute(sql, params)
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]

    def prints_between(self, start: date, end: date) -> list[dict[str, Any]]:
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, report_date, session, source
                      FROM {self._schema}.earnings_calendar
                     WHERE report_date BETWEEN %s AND %s
                     ORDER BY report_date, ticker""",
                (start, end),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
