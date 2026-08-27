"""Nightly implied-move snapshot store (spec §5-iii): what the options market
currently implies the next print will do, derived from
`option_surface_grid_daily`. See migration 146 for the formula and the
absence-of-row-is-coverage rule.

Standalone repository, not a `Repository` mixin — same rationale as
`earnings_calendar.py` / `earnings_reactions.py`: `repository.py` is closed
to new query methods, and this is its own domain.

WHY UPSERT OVERWRITES (unlike `earnings_reactions`' insert-or-skip)
--------------------------------------------------------------------
A reaction row is a completed historical fact — once both closes are
observed it never changes, so a replay must never silently recompute it.
An implied-move row is the opposite: it is TONIGHT'S read of the surface for
a print that hasn't happened yet, and the PK is (ticker, market_date), not
(ticker, report_date) — a rerun on the same night (retry after a transient
failure, a manual backfill re-pass) should overwrite with the freshest
recompute, not skip. `upsert_rows` therefore reports rows genuinely NEW via
`xmax = 0`, matching the honesty rule from `earnings_calendar.py` /
`earnings_reactions.py` — a replay of an already-computed night returns 0,
not `len(rows)`, even though every row's `computed_at` still advances.
"""

from __future__ import annotations

from collections.abc import Sequence
from datetime import date
from typing import Any

import psycopg


class ImpliedMoveRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert_rows(self, rows: Sequence[dict[str, Any]]) -> int:
        """Insert-or-replace one row per (ticker, market_date). Returns rows
        genuinely NEW (measured via `xmax = 0`, not assumed from `len(rows)`
        — a same-night replay must report zero new rows, honestly)."""
        if not rows:
            return 0
        table = f"{self._schema}.implied_move_daily"
        sql = f"""
            INSERT INTO {table}
                        (ticker, market_date, report_date, expiry, strike,
                         atm_iv, iv_basis, spot, implied_move_pct, implied_move_usd)
                 VALUES (%(ticker)s, %(market_date)s, %(report_date)s, %(expiry)s,
                         %(strike)s, %(atm_iv)s, %(iv_basis)s, %(spot)s,
                         %(implied_move_pct)s, %(implied_move_usd)s)
            ON CONFLICT (ticker, market_date) DO UPDATE SET
                 report_date      = EXCLUDED.report_date,
                 expiry           = EXCLUDED.expiry,
                 strike           = EXCLUDED.strike,
                 atm_iv           = EXCLUDED.atm_iv,
                 iv_basis         = EXCLUDED.iv_basis,
                 spot             = EXCLUDED.spot,
                 implied_move_pct = EXCLUDED.implied_move_pct,
                 implied_move_usd = EXCLUDED.implied_move_usd,
                 computed_at      = now()
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

    def latest_for(self, tickers: Sequence[str]) -> dict[str, dict[str, Any]]:
        """Newest `market_date` row per ticker. The PK is (ticker,
        market_date) so there is already at most one row per ticker per
        night — "latest" just means the one row a bulk caller asked for by
        ticker set, keyed by upper-cased ticker."""
        if not tickers:
            return {}
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT ON (ticker)
                           ticker, market_date, report_date, expiry, strike,
                           atm_iv, iv_basis, spot, implied_move_pct,
                           implied_move_usd, computed_at
                      FROM {self._schema}.implied_move_daily
                     WHERE ticker = ANY(%s)
                     ORDER BY ticker, market_date DESC""",
                ([t.upper() for t in tickers],),
            )
            cols = [d.name for d in cur.description]
            return {row[0]: dict(zip(cols, row)) for row in cur.fetchall()}

    def history(self, ticker: str, report_date: date) -> list[dict[str, Any]]:
        """Every nightly snapshot that targeted this ONE upcoming print,
        oldest first — the day-by-day path the implied move took as the desk
        approached the report date. The delta-rail shift-event reader reads
        this to find where the number jumped between two consecutive
        nights."""
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT ticker, market_date, report_date, expiry, strike,
                           atm_iv, iv_basis, spot, implied_move_pct,
                           implied_move_usd, computed_at
                      FROM {self._schema}.implied_move_daily
                     WHERE ticker = %s AND report_date = %s
                     ORDER BY market_date ASC""",
                (ticker.upper(), report_date),
            )
            cols = [d.name for d in cur.description]
            return [dict(zip(cols, r)) for r in cur.fetchall()]
