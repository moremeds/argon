"""Does UW's dating simply lag a quarter, or does it stop permanently?

Prints UW's period -> filing_date map next to our panel's, newest first.
"""
import httpx, psycopg
from uw_scan.config import Settings
s = Settings.from_env()
h = {"Authorization": f"Bearer {s.api_key.get_secret_value()}", "Accept": "application/json"}
B = "https://api.unusualwhales.com"
conn = psycopg.connect(s.db_dsn())
cur = conn.cursor()
with httpx.Client(timeout=30.0) as c:
    for t in ("WMT", "AEP", "BABA", "ARM", "AAPL"):
        r = c.get(f"{B}/api/stock/{t}/fundamental-breakdown", headers=h)
        gen = (r.json().get("data") or {}).get("general") or [] if r.status_code == 200 else []
        uw = {}
        for row in gen:
            pe = row.get("report_period_end_date")
            if pe:
                uw[str(pe)[:10]] = str(row.get("filing_date"))[:10] if row.get("filing_date") else None
        cur.execute(f"""
            SELECT period_end, max(filing_published_at)
              FROM {s.db_schema}.fundamental_statement_obs
             WHERE ticker=%s AND period_type='quarterly' AND period_end >= date '2025-06-01'
          GROUP BY period_end ORDER BY period_end DESC
        """, (t,))
        ours = cur.fetchall()
        print(f"\n=== {t}   UW general rows={len(gen)}  UW periods with a date="
              f"{sum(1 for v in uw.values() if v)}/{len(uw)}")
        for pe, fp in ours:
            k = pe.isoformat()
            print(f"   period={k}  ours={fp}  uw={uw.get(k, '<period absent from UW breakdown>')}")
conn.close()
