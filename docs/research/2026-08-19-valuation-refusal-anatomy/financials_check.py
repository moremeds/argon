"""Read-only: are deposit-funded financials being GIVEN a band, not just refused?"""
import psycopg
from uw_scan.config import Settings

BANKS = ('BAC','GS','JPM','MS','WFC','C','SCHW','FLG','HOOD','BLK','AXP','COF',
         'USB','PNC','TFC','BK','STT','ALLY','SOFI','NU','ICE','CME','SPGI','V','MA')
s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute("SELECT max(as_of) FROM uw_scan.valuation_anchors")
    as_of = cur.fetchone()[0]
    cur.execute(
        """SELECT ticker, company_type, method, buy_below, spot, spot_percentile,
                  risk_above, confidence
           FROM uw_scan.valuation_anchors
           WHERE as_of=%s AND ticker = ANY(%s) ORDER BY ticker""",
        (as_of, list(BANKS)),
    )
    rows = cur.fetchall()
print(f"as_of={as_of}\n{'tkr':<6}{'company_type':<22}{'method':<14}{'buy_below':>11}{'spot':>10}{'pct':>7}  conf")
for t, ct, m, bb, sp, pct, ra, conf in rows:
    f = lambda v: f"{float(v):.2f}" if v is not None else "—"
    print(f"{t:<6}{ct or '—':<22}{m or '—':<14}{f(bb):>11}{f(sp):>10}{(f'{float(pct):.2f}' if pct is not None else '—'):>7}  {conf}")

# and: is there ANY company_type that names financials?
with psycopg.connect(s.db_dsn()) as c2, c2.cursor() as cur2:
    cur2.execute("SELECT company_type, count(*) FROM uw_scan.valuation_anchors "
                 "WHERE as_of=%s GROUP BY 1 ORDER BY 2 DESC", (as_of,))
    print("\ncompany_type distribution:")
    for ct, n in cur2.fetchall():
        print(f"  {n:4d}  {ct}")
