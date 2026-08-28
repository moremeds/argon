"""Nightly per-name desk rollup store (spec §3c, Task 12): revenue YoY and
gross-margin trajectory, one row per (ticker, period_end), computed by
`worker/jobs/fundamentals_desk_rollup.py` so the chain x metric matrix reads
it at request time with zero recompute.

Standalone repository, not a `Repository` mixin -- same rationale as
`earnings_calendar.py` / `implied_move.py`: `repository.py` is closed to new
query methods, and this is its own domain.

WHY UPSERT OVERWRITES (unlike `earnings_reactions`' insert-or-skip)
--------------------------------------------------------------------
A period's rollup is not a completed historical fact the way a realised
earnings reaction is. The statement store is append-only (a restatement lands
as a NEW `obs_id` beside the old one) and violations can be recorded or
cleared retroactively (`FundamentalObsRepository.recheck_violations`), so the
correct rev_yoy/gross_margin for an already-rolled-up period can change
between two nightly runs. The PK is (ticker, period_end), and a rerun should
overwrite with the freshest recompute -- same shape as `ImpliedMoveRepository.
upsert_rows`, not `EarningsReactionsRepository`'s.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

import psycopg


class FundamentalsDeskRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert-or-replace one row per (ticker, period_end). Returns rows
        genuinely NEW (measured via `xmax = 0`, not assumed from `len(rows)`
        -- a same-night replay must report zero new rows, honestly, even
        though every row's `computed_at` still advances)."""
        if not rows:
            return 0
        table = f"{self._schema}.fundamentals_desk_rollup"
        sql = f"""
            INSERT INTO {table}
                        (ticker, period_end, rev_yoy, gross_margin, gross_profit,
                         knowledge_date)
                 VALUES (%(ticker)s, %(period_end)s, %(rev_yoy)s, %(gross_margin)s,
                         %(gross_profit)s, %(knowledge_date)s)
            ON CONFLICT (ticker, period_end) DO UPDATE SET
                 rev_yoy        = EXCLUDED.rev_yoy,
                 gross_margin   = EXCLUDED.gross_margin,
                 gross_profit   = EXCLUDED.gross_profit,
                 knowledge_date = EXCLUDED.knowledge_date,
                 computed_at    = now()
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

    def latest_per_ticker(self, tickers: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Newest `period_end` row per ticker -- what a matrix cell shows.
        Absent from the return dict, not a null-valued entry, for a ticker
        with no rollup row at all."""
        if not tickers:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (ticker)
                           ticker, period_end, rev_yoy, gross_margin, gross_profit,
                           knowledge_date, computed_at
                      FROM {self._schema}.fundamentals_desk_rollup
                     WHERE ticker = ANY(%s)
                     ORDER BY ticker, period_end DESC""",
                ([t.upper() for t in tickers],),
            )
            cols = [d.name for d in cur.description]
            return {row[0]: dict(zip(cols, row)) for row in cur.fetchall()}

    def trajectory(self, ticker: str, quarters: int = 8) -> list[dict[str, Any]]:
        """Newest-first, most recent `quarters` periods for one ticker."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, period_end, rev_yoy, gross_margin, gross_profit,
                           knowledge_date, computed_at
                      FROM {self._schema}.fundamentals_desk_rollup
                     WHERE ticker = %s
                     ORDER BY period_end DESC
                     LIMIT %s""",
                (ticker.upper(), quarters),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
