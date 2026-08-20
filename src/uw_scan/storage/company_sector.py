"""Vendor sector cache — read by `company_type` routing, written by its fetch job.

Its own module rather than a `Repository` method: `repository.py` is closed to new
query methods (see the root CLAUDE.md module-size rule), and this is a distinct
domain — a vendor vocabulary, not part of the anchor pipeline that consumes it.

Table shape and the reason a NULL sector is stored rather than skipped:
`storage/migrations/123_company_sector.sql`.
"""

from __future__ import annotations

from typing import Any

import psycopg


class CompanySectorRepository:
    def __init__(self, conn: psycopg.Connection, *, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def upsert(self, ticker: str, sector: str | None, *, source: str = "uw") -> None:
        """Record what the vendor said, including that it said nothing.

        Always bumps `fetched_at`, even when the sector is unchanged — the column
        answers "when did we last ask", which is what the fetch job's staleness
        ordering needs. A conditional update would make an unchanging name look
        never-refreshed and hold it at the front of the queue forever.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""INSERT INTO {self._schema}.company_sector
                           (ticker, sector, source, fetched_at)
                    VALUES (%s, %s, %s, now())
                    ON CONFLICT (ticker) DO UPDATE
                       SET sector = EXCLUDED.sector,
                           source = EXCLUDED.source,
                           fetched_at = now()""",
                (ticker.upper(), sector, source),
            )
        self.conn.commit()

    def tickers_needing_fetch(self, limit: int) -> list[str]:
        """Universe names with no sector row yet.

        Joined on `upper(f.ticker)` because `upsert` stores the uppercase form.
        Every ticker in the universe is uppercase today and nothing enforces it;
        a lowercase one would be asked, written uppercase, then fail this join
        and be asked again every month forever — one UW call per name, silently.

        Only names absent from the table: a recorded NULL means the vendor was
        asked and had no sector, and re-asking it every run would spend the
        budget on the one answer that cannot change the routing. A periodic
        re-ask belongs in a separate refresh pass keyed on `fetched_at` — not
        built, and not indexed for, until something needs it.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT DISTINCT f.ticker
                      FROM {self._schema}.fundamental_universe f
                      LEFT JOIN {self._schema}.company_sector c
                             ON c.ticker = upper(f.ticker)
                     WHERE f.removed_at IS NULL AND c.ticker IS NULL
                     ORDER BY f.ticker
                     LIMIT %s""",
                (limit,),
            )
            return [r[0] for r in cur.fetchall()]

    def coverage(self) -> dict[str, Any]:
        """`(universe, with a row, with a non-null sector)` — for the job log.

        `count(DISTINCT ...)` on every leg and `upper()` on the join for the same
        two reasons `tickers_needing_fetch` needs them: the universe holds one row
        per (tier, ticker) — 475 rows for 450 names on 2026-08-20 — and `upsert`
        stores the uppercase ticker. Get either wrong and the log reports a
        coverage shortfall that the fetch loop cannot close, run after run.
        """
        with self.conn.cursor() as cur:
            cur.execute(
                f"""SELECT count(DISTINCT f.ticker) AS universe,
                           count(DISTINCT c.ticker) AS fetched,
                           count(DISTINCT c.ticker) FILTER (
                               WHERE c.sector IS NOT NULL) AS classified
                      FROM {self._schema}.fundamental_universe f
                      LEFT JOIN {self._schema}.company_sector c
                             ON c.ticker = upper(f.ticker)
                     WHERE f.removed_at IS NULL"""
            )
            row = cur.fetchone() or (0, 0, 0)
            return {"universe": row[0], "fetched": row[1], "classified": row[2]}
