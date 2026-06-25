"""Persistence for data-date freshness snapshots (prevention layer). New
domain — own file (never appended to repository.py)."""

from __future__ import annotations

from datetime import date

from psycopg import Connection

from uw_scan.reports.data_freshness import FreshnessRow


class DataFreshnessRepository:
    def __init__(self, conn: Connection, schema: str = "uw_scan") -> None:
        self._conn = conn
        self._schema = schema
        with conn.cursor() as cur:
            cur.execute(f"SET search_path TO {schema}, public")

    def upsert_snapshot(self, run_date: date, rows: list[FreshnessRow]) -> int:
        if not rows:
            return 0
        params = [
            {
                "run_date": run_date,
                "table_name": r.table_name,
                "date_col": r.date_col,
                "scope": r.scope,
                "expected_count": r.expected_count,
                "covered_count": r.covered_count,
                "coverage_pct": r.coverage_pct,
                "max_data_date": r.max_data_date,
                "days_stale": r.days_stale,
                "frozen": r.frozen,
            }
            for r in rows
        ]
        sql = """
            INSERT INTO data_freshness_snapshots
                (run_date, table_name, date_col, scope, expected_count,
                 covered_count, coverage_pct, max_data_date, days_stale, frozen)
            VALUES
                (%(run_date)s, %(table_name)s, %(date_col)s, %(scope)s,
                 %(expected_count)s, %(covered_count)s, %(coverage_pct)s,
                 %(max_data_date)s, %(days_stale)s, %(frozen)s)
            ON CONFLICT (run_date, table_name) DO UPDATE SET
                date_col       = EXCLUDED.date_col,
                scope          = EXCLUDED.scope,
                expected_count = EXCLUDED.expected_count,
                covered_count  = EXCLUDED.covered_count,
                coverage_pct   = EXCLUDED.coverage_pct,
                max_data_date  = EXCLUDED.max_data_date,
                days_stale     = EXCLUDED.days_stale,
                frozen         = EXCLUDED.frozen
        """
        with self._conn.cursor() as cur:
            cur.executemany(sql, params)
        self._conn.commit()
        return len(params)

    def latest_snapshot(self) -> list[dict]:
        sql = """
            SELECT table_name, date_col, scope, expected_count, covered_count,
                   coverage_pct, max_data_date, days_stale, frozen
              FROM data_freshness_snapshots
             WHERE run_date = (SELECT MAX(run_date) FROM data_freshness_snapshots)
             ORDER BY frozen DESC, coverage_pct ASC NULLS FIRST, table_name
        """
        with self._conn.cursor() as cur:
            cur.execute(sql)
            cols = [c.name for c in cur.description]
            return [dict(zip(cols, row, strict=True)) for row in cur.fetchall()]
