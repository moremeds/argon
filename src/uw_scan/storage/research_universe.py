"""Named research ticker cohorts (`uw_scan.research_universe`, migration 110).

Deliberately separate from the watchlist. Watchlist membership enlists a ticker
in every per-ticker scheduled job; a research cohort only needs to be iterable by
its own capture job and groupable by its tags in analysis SQL.

Standalone repository rather than a Repository mixin — new persistence domains
get their own module from method one (see the storage split rule in CLAUDE.md).
"""

from __future__ import annotations

from typing import Any

import psycopg


class ResearchUniverseRepository:
    def __init__(self, conn: psycopg.Connection, schema: str = "uw_scan") -> None:
        self.conn = conn
        self._schema = schema

    def list_cohort_tickers(self, cohort: str) -> list[str]:
        """Tickers in a cohort, stable order.

        Returns [] for an unknown cohort rather than raising: the nightly capture
        job is gated on this being non-empty, so an unseeded cohort must read as
        "nothing to do" and spend zero UW calls, not as a crash.
        """
        sql = f"""
            SELECT ticker FROM {self._schema}.research_universe
             WHERE cohort = %s ORDER BY ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (cohort,))
            return [r[0] for r in cur.fetchall()]

    def list_cohort(self, cohort: str) -> list[dict[str, Any]]:
        """Full cohort rows including the tags analysis groups on."""
        sql = f"""
            SELECT ticker, sector, marketcap, option_oi, selected_on
              FROM {self._schema}.research_universe
             WHERE cohort = %s ORDER BY sector, ticker
        """
        with self.conn.cursor() as cur:
            cur.execute(sql, (cohort,))
            return [
                {
                    "ticker": r[0],
                    "sector": r[1],
                    "marketcap": r[2],
                    "option_oi": r[3],
                    "selected_on": r[4],
                }
                for r in cur.fetchall()
            ]
