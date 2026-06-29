"""Persistence for Top Net Impact snapshots.

New domain — own file, never extending repository.py. One row per
(session date, ticker); each capture upserts the ticker's current cumulative
net premium, so re-fetching the same day overwrites the same rows (idempotent).
"""

from __future__ import annotations

from collections import defaultdict
from datetime import date

from psycopg import Connection


class TopNetImpactRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_rows(self, rows: list[dict]) -> int:
        """Upsert net premium + rank for each (data_date, ticker). On conflict,
        the row's existing `rank` is carried into `prev_rank` BEFORE being
        overwritten — that one move is what makes the per-update rank delta work
        (rank_change = prev_rank - rank, computed at read). Tickers absent from
        the newest same-date capture are deleted so the read path reflects the
        latest UW ranking membership instead of a union of prior captures."""
        if not rows:
            return 0
        by_date: dict[date, set[str]] = defaultdict(set)
        for row in rows:
            by_date[row["data_date"]].add(str(row["ticker"]).upper())
        sql = """
            INSERT INTO top_net_impact_snapshots
                (data_date, ticker, net_premium, rank, prev_rank)
            VALUES (%(data_date)s, %(ticker)s, %(net_premium)s, %(rank)s, NULL)
            ON CONFLICT (data_date, ticker) DO UPDATE
               SET prev_rank   = top_net_impact_snapshots.rank,
                   rank        = EXCLUDED.rank,
                   net_premium = EXCLUDED.net_premium,
                   captured_at = now()
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, rows)
            for data_date, tickers in by_date.items():
                cur.execute(
                    """
                    DELETE FROM top_net_impact_snapshots
                     WHERE data_date = %s
                       AND NOT (ticker = ANY(%s))
                    """,
                    (data_date, list(tickers)),
                )
        self._conn.commit()
        return len(rows)

    def fetch_latest(
        self, *, data_date: date | None = None, limit: int = 40
    ) -> tuple[date | None, list[dict]]:
        """Rows for the requested session (or the most recent one when
        ``data_date`` is None). Returns the ``limit`` most-impactful tickers
        SPLIT between bullish and bearish — top ⌈limit/2⌉ by net_premium plus
        bottom ⌊limit/2⌋ — so both extremes show (a plain DESC LIMIT would drop
        the most bearish). Sorted by net_premium DESC. ([] when no rows exist).
        """
        if data_date is None:
            with self._conn.cursor() as cur:
                cur.execute("SELECT max(data_date) FROM top_net_impact_snapshots")
                row = cur.fetchone()
                data_date = row[0] if row else None
        if data_date is None:
            return None, []
        top = (limit + 1) // 2
        bot = limit // 2
        sql = """
            WITH base AS (
                SELECT ticker,
                       net_premium::float8 AS net_premium,
                       rank,
                       prev_rank,
                       CASE WHEN prev_rank IS NULL THEN NULL
                            ELSE prev_rank - rank END AS rank_change
                  FROM top_net_impact_snapshots
                 WHERE data_date = %(d)s
            )
            SELECT * FROM (
                (SELECT * FROM base ORDER BY net_premium DESC LIMIT %(top)s)
                UNION
                (SELECT * FROM base ORDER BY net_premium ASC LIMIT %(bot)s)
            ) u
            ORDER BY net_premium DESC
        """
        with self._conn.cursor() as cur:
            cur.execute(sql, {"d": data_date, "top": top, "bot": bot})
            cols = [c.name for c in cur.description]
            rows = [dict(zip(cols, r, strict=True)) for r in cur.fetchall()]
        return data_date, rows
