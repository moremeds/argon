"""Split a data_gap_healer audit run into loss vs never-captured.

The audit counts a gap for every (dataset, session, ticker) the calendar says
should exist, with no notion of when the dataset began or when the ticker joined
the watchlist. Run 91 (2026-01-01..2026-08-17) therefore reported 230,934 gaps
and meant 978. This script derives each dataset's first-ever row date directly
from the table (the registry's date_col is NULL for 18 of 23 datasets) and
buckets every item.

Reproduce (read-only, ZERO provider calls; run inside a worker container so the
DB env is already set):

  docker exec -i argon-worker-uw-0-1 python - \
    < docs/research/_scripts/2026-08-17-classify-gap-buckets.py 91
"""

from __future__ import annotations

import os
import sys

import psycopg

# First column present wins; mirrors the ad-hoc introspection used to measure.
DATE_CANDIDATES = (
    "data_date",
    "market_date",
    "snapshot_date",
    "trade_date",
    "curr_date",
    "as_of_date",
    "date",
)


def first_row_date(cur, schema: str, table: str) -> tuple[str | None, object]:
    cur.execute(
        """SELECT column_name FROM information_schema.columns
            WHERE table_schema = %s AND table_name = %s""",
        (schema, table),
    )
    cols = {r[0] for r in cur.fetchall()}
    col = next((c for c in DATE_CANDIDATES if c in cols), None)
    if col is None:
        return None, None
    cur.execute(f"SELECT min({col})::date FROM {schema}.{table}")
    return col, cur.fetchone()[0]


def main() -> int:
    run_id = int(sys.argv[1]) if len(sys.argv) > 1 else 91
    schema = os.environ.get("UW_SCAN_DB_SCHEMA", "uw_scan")
    dsn = (
        f"host={os.environ['UW_SCAN_DB_HOST']} port={os.environ.get('UW_SCAN_DB_PORT', 5432)} "
        f"dbname={os.environ['UW_SCAN_DB_NAME']} user={os.environ['UW_SCAN_DB_USER']} "
        f"password={os.environ['UW_SCAN_DB_PASSWORD']}"
    )
    with psycopg.connect(dsn) as conn, conn.cursor() as cur:
        cur.execute(
            "SELECT DISTINCT dataset FROM %s.data_gap_items WHERE run_id = %%s"
            % schema,
            (run_id,),
        )
        datasets = sorted(r[0] for r in cur.fetchall())

        print(f"{'dataset':<34} {'first_row':>12} {'gaps':>7} "
              f"{'pre_table':>9} {'pre_member':>10} {'REAL':>7}")
        totals = [0, 0, 0, 0]
        for ds in datasets:
            _, first = first_row_date(cur, schema, ds)
            cur.execute(
                f"""
                SELECT count(*),
                  count(*) FILTER (
                    WHERE %s::date IS NOT NULL AND i.data_date < %s::date),
                  count(*) FILTER (
                    WHERE NOT (%s::date IS NOT NULL AND i.data_date < %s::date)
                      AND i.ticker IS NOT NULL
                      AND w.added_at::date > i.data_date),
                  count(*) FILTER (
                    WHERE NOT (%s::date IS NOT NULL AND i.data_date < %s::date)
                      AND NOT (i.ticker IS NOT NULL
                               AND w.added_at::date > i.data_date))
                  FROM {schema}.data_gap_items i
                  LEFT JOIN {schema}.watchlist w ON w.ticker = i.ticker
                 WHERE i.run_id = %s AND i.dataset = %s
                """,
                (first, first, first, first, first, first, run_id, ds),
            )
            n, pre_table, pre_member, real = cur.fetchone()
            for i, v in enumerate((n, pre_table, pre_member, real)):
                totals[i] += v
            if n:
                print(f"{ds:<34} {str(first):>12} {n:>7} "
                      f"{pre_table:>9} {pre_member:>10} {real:>7}")
        print(f"{'TOTAL':<34} {'':>12} {totals[0]:>7} "
              f"{totals[1]:>9} {totals[2]:>10} {totals[3]:>7}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
