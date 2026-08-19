"""Realised valuation-band coverage and buy-zone membership on a live DB.

D5 of `docs/superpowers/plans/2026-08-13-fundamental-lane-next.md` requires the
universe widening to be verified by the **realised** band count rather than by
the projected one, after that decision was once reversed by a coverage number
measured on the wrong host. This is the script that produces it.

It calls `FundamentalAnchorsRepository.band_coverage` and `.in_buy_zone` — the
same methods `GET /api/scanner/value` serves from — so what it reports is the
shipped read path and not a second opinion about it. A parallel hand-written
query would verify itself.

Reproduce (mini, inside the worker container so the DSN is the prod one):

    docker cp scripts/research/valuation_band_coverage_check.py \\
        argon-worker-massive-0-1:/tmp/ && \\
    docker exec argon-worker-massive-0-1 \\
        python /tmp/valuation_band_coverage_check.py

Read-only: no writes, no external calls.
"""

from __future__ import annotations

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository


def main() -> None:
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        schema = settings.db_schema
        engine = FundamentalScoresRepository(conn, schema=schema).active_version()
        if engine is None:
            print("no active fundamental method version")
            return
        anchors = FundamentalAnchorsRepository(conn, schema=schema)
        as_of, banded = anchors.band_coverage(engine)
        print(f"engine           {engine}")
        print(f"as_of            {as_of}")
        print(f"banded universe  {banded}")

        # Accrual by as_of. "banded" counts a usable band (buy_below present);
        # a REFUSED row carries every level null and is not coverage.
        with conn.cursor() as cur:
            cur.execute(
                f"""SELECT as_of, count(DISTINCT ticker) AS names,
                           count(DISTINCT ticker)
                             FILTER (WHERE buy_below IS NOT NULL) AS banded
                      FROM {schema}.valuation_anchors
                     WHERE engine_version = %s
                     GROUP BY as_of ORDER BY as_of DESC LIMIT 8""",
                (engine,),
            )
            print("\nas_of        names  banded")
            for row in cur.fetchall():
                print(f"{row[0]}  {row[1]:>5}  {row[2]:>6}")

        rows = anchors.in_buy_zone(engine)
        counts = {
            state: sum(1 for r in rows if r["entered"] is state)
            for state in (True, False, None)
        }
        print(f"\nin buy zone      {len(rows)} of {banded}")
        print(f"  newly entered  {counts[True]}")
        print(f"  already in     {counts[False]}")
        print(f"  no prior band  {counts[None]}  (unknown, NOT new)")
        print("  first 12:", ", ".join(r["ticker"] for r in rows[:12]))

        # PR-2 step 3: does `spot_percentile` move between sessions? It is a
        # rank over `history_quarters` observations, so it can only take steps
        # of 1/history_quarters — a name holding its value across a 3-day gap is
        # the construction working, not a frozen field.
        with conn.cursor() as cur:
            cur.execute(
                f"""
                WITH d AS (
                    SELECT DISTINCT as_of FROM {schema}.valuation_anchors
                     WHERE engine_version = %s ORDER BY as_of DESC LIMIT 2
                ),
                r AS (
                    SELECT DISTINCT ON (ticker, as_of) ticker, as_of, spot_percentile
                      FROM {schema}.valuation_anchors
                     WHERE engine_version = %s AND as_of IN (SELECT as_of FROM d)
                     ORDER BY ticker, as_of DESC, result_id DESC
                )
                SELECT count(*),
                       count(*) FILTER (WHERE a.spot_percentile <> b.spot_percentile),
                       max(abs(a.spot_percentile - b.spot_percentile)),
                       min(a.as_of), max(a.as_of)
                  FROM r a JOIN r b USING (ticker)
                 WHERE a.as_of > b.as_of
                   AND a.spot_percentile IS NOT NULL
                   AND b.spot_percentile IS NOT NULL
                """,
                (engine, engine),
            )
            paired, moved, largest, *_ = cur.fetchone()
            pct = (moved / paired * 100) if paired else 0.0
            print(
                f"\npercentile movement across the two newest as_of values:"
                f"\n  paired {paired}  moved {moved} ({pct:.1f}%)  largest {largest}"
            )


if __name__ == "__main__":
    main()
