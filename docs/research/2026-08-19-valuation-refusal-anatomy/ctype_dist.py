import psycopg
from uw_scan.config import Settings
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute("SELECT max(as_of) FROM uw_scan.valuation_anchors")
    as_of = cur.fetchone()[0]
    cur.execute("""SELECT company_type, method, count(*) FILTER (WHERE buy_below IS NOT NULL) banded,
                          count(*) FILTER (WHERE buy_below IS NULL) refused
                   FROM uw_scan.valuation_anchors WHERE as_of=%s
                   GROUP BY 1,2 ORDER BY 3+4 DESC""", (as_of,))
    print(f"as_of={as_of}\n{'company_type':<22}{'method':<14}{'banded':>7}{'refused':>9}")
    for ct, m, b, r in cur.fetchall():
        print(f"{ct or '—':<22}{m or '—':<14}{b:>7}{r:>9}")
