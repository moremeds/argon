"""What periods does fundamental-breakdown actually carry, and how far behind
the statement endpoints is its frontier?

If breakdown trails statements by ~a quarter, then every ingest of a
just-reported quarter stores filing_published_at=NULL, and the current
ON CONFLICT (which refreshes only last_seen_at) can never fill it in later.
"""
import httpx, psycopg, json
from uw_scan.config import Settings
s = Settings.from_env()
h = {"Authorization": f"Bearer {s.api_key.get_secret_value()}", "Accept": "application/json"}
B = "https://api.unusualwhales.com"
conn = psycopg.connect(s.db_dsn()); cur = conn.cursor()

with httpx.Client(timeout=30.0) as c:
    r = c.get(f"{B}/api/stock/AAPL/fundamental-breakdown", headers=h)
    gen = (r.json().get("data") or {}).get("general") or []
    print("AAPL breakdown: first row keys ->", sorted(gen[0].keys())[:20] if gen else "EMPTY")
    print("AAPL breakdown periods (newest 8):")
    for row in sorted(gen, key=lambda x: str(x.get("report_period_end_date")), reverse=True)[:8]:
        print("   ", {k: row.get(k) for k in
              ("report_period_end_date", "filing_date", "report_type", "fiscal_year", "fiscal_quarter")})

    # Frontier gap across a sample of the universe
    cur.execute(f"""
        SELECT ticker, max(period_end)
          FROM {s.db_schema}.fundamental_statement_obs
         WHERE period_type='quarterly' GROUP BY ticker ORDER BY random() LIMIT 40
    """)
    sample = cur.fetchall()
    gaps = []
    for t, newest_stmt in sample:
        rr = c.get(f"{B}/api/stock/{t}/fundamental-breakdown", headers=h)
        if rr.status_code != 200:
            continue
        g = (rr.json().get("data") or {}).get("general") or []
        periods = sorted(str(x.get("report_period_end_date"))[:10] for x in g
                         if x.get("report_period_end_date"))
        if not periods:
            gaps.append((t, newest_stmt.isoformat(), None, None)); continue
        from datetime import date
        nb = date.fromisoformat(periods[-1])
        gaps.append((t, newest_stmt.isoformat(), periods[-1], (newest_stmt - nb).days))

print("\nticker | newest QUARTERLY in statements | newest in breakdown | gap days")
for t, ns, nb, g in gaps:
    print(f"  {t:<7} {ns}   {str(nb):<12} {g}")
vals = [g for *_ , g in gaps if g is not None]
vals.sort()
print(f"\nn={len(vals)}  p50={vals[len(vals)//2] if vals else None}  "
      f"min={vals[0] if vals else None}  max={vals[-1] if vals else None}  "
      f"gap>0 (breakdown behind): {sum(1 for v in vals if v > 0)}/{len(vals)}")
conn.close()
