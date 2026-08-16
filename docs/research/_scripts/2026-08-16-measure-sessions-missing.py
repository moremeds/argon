"""Compute the NEW sessions_missing metric against live prod data.

Same definition as reports/data_freshness.compute_freshness: the last 5 expected
sessions from the UNIONED spine; a session counts missing when distinct-ticker
coverage is below LOW_COVERAGE_PCT = 0.5.
"""

import psycopg

from uw_scan.config import Settings
from uw_scan.reports.data_freshness import (
    MONITORED_TABLES,
    _detect_date_col,
    _ticker_col,
)

s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as c, c.cursor() as cur:
    cur.execute(
        """
        SELECT d FROM (
          SELECT DISTINCT data_date AS d FROM uw_scan.market_tide_sentiment_daily
           WHERE data_date >= current_date - 15
          UNION
          SELECT DISTINCT date AS d FROM uw_scan.daily_ohlc
           WHERE ticker='SPY' AND date >= current_date - 15
        ) x ORDER BY d DESC LIMIT 5
        """
    )
    sessions = sorted(r[0] for r in cur.fetchall())
    print("spine (last 5 expected sessions):", [str(d) for d in sessions])
    cur.execute("SELECT count(*) FROM uw_scan.watchlist WHERE removed_at IS NULL")
    n_exp = cur.fetchone()[0]
    print("expected watchlist tickers:", n_exp)
    print()
    print("%-38s %8s %12s  per-session counts" % ("table", "cov_pct", "sess_miss"))
    for mt in MONITORED_TABLES:
        if mt.scope != "watchlist":
            continue
        dcol = mt.date_col_override or _detect_date_col(c, s.db_schema, mt.name)
        tcol = _ticker_col(c, s.db_schema, mt.name)
        if not dcol or not tcol:
            continue
        try:
            cur.execute(
                f"SELECT s.d, COUNT(DISTINCT UPPER(a.{tcol}))::int "
                f"FROM unnest(%s::date[]) s(d) LEFT JOIN uw_scan.{mt.name} a "
                f"ON a.{dcol} = s.d GROUP BY s.d ORDER BY s.d",
                (sessions,),
            )
            per = cur.fetchall()
        except Exception as exc:
            c.rollback()
            print("%-38s  ERR %r" % (mt.name, exc))
            continue
        missing = sum(1 for _, n in per if n < n_exp * 0.5)
        cur.execute(
            "SELECT round(coverage_pct::numeric,3) FROM "
            "uw_scan.data_freshness_snapshots WHERE table_name=%s "
            "ORDER BY run_date DESC LIMIT 1",
            (mt.name,),
        )
        r = cur.fetchone()
        cov = str(r[0]) if r and r[0] is not None else "-"
        hidden = missing and cov != "-" and float(cov) >= 0.9
        print(
            "%-38s %8s %12d  %s%s"
            % (
                mt.name,
                cov,
                missing,
                [n for _, n in per],
                "  <== HIDDEN BY cov_pct" if hidden else "",
            )
        )
