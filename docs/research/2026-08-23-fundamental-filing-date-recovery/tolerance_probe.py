"""How many NULL filing dates does TOLERANT period matching recover?

fundamental_ingest._filing_dates keys breakdown rows by their true fiscal
period end (AAPL 2026-06-27) and looks them up with the statement endpoints'
calendar-month-end period (2026-06-30). For every 52/53-week filer that exact
lookup misses on every period, forever.

Measures recovery at several day tolerances so the plan can pick one.
"""
import json
from datetime import date
import httpx, psycopg
from uw_scan.config import Settings

s = Settings.from_env()
h = {"Authorization": f"Bearer {s.api_key.get_secret_value()}", "Accept": "application/json"}
B = "https://api.unusualwhales.com"
TOL = (0, 3, 5, 7, 10, 14)

conn = psycopg.connect(s.db_dsn()); cur = conn.cursor()
cur.execute(f"""
    SELECT ticker
      FROM {s.db_schema}.fundamental_statement_obs
     WHERE period_type='quarterly' AND period_end >= date '2024-01-01'
  GROUP BY ticker
    HAVING count(*) FILTER (WHERE filing_published_at IS NULL) > 0
  ORDER BY ticker
""")
cand = [r[0] for r in cur.fetchall()]
print(f"TICKERS_WITH_ANY_NULL={len(cand)}", flush=True)

rec = {t: 0 for t in TOL}
periods_checked = 0
rows_by_tol = {t: 0 for t in TOL}
ambiguous = 0
examples = []

with httpx.Client(timeout=30.0) as c:
    for tk in cand:
        r = c.get(f"{B}/api/stock/{tk}/fundamental-breakdown", headers=h)
        if r.status_code != 200:
            continue
        bd = []
        for row in (r.json().get("data") or {}).get("general") or []:
            pe, fd = row.get("report_period_end_date"), row.get("filing_date")
            if pe and fd:
                bd.append((date.fromisoformat(str(pe)[:10]), str(fd)[:10]))
        if not bd:
            continue
        cur.execute(f"""
            SELECT period_end, count(*)
              FROM {s.db_schema}.fundamental_statement_obs
             WHERE ticker=%s AND period_type='quarterly'
               AND filing_published_at IS NULL AND period_end >= date '2024-01-01'
          GROUP BY period_end
        """, (tk,))
        for pe, nrows in cur.fetchall():
            periods_checked += 1
            for tol in TOL:
                near = [(abs((bp - pe).days), bp, fd) for bp, fd in bd
                        if abs((bp - pe).days) <= tol]
                if near:
                    rec[tol] += 1
                    rows_by_tol[tol] += nrows
                    if tol == 7 and len(near) > 1:
                        ambiguous += 1
                    if tol == 7 and len(examples) < 12:
                        near.sort()
                        examples.append((tk, pe.isoformat(), near[0][1].isoformat(), near[0][2], near[0][0]))

print(json.dumps({
    "null_periods_checked": periods_checked,
    "periods_recovered_by_tolerance": rec,
    "statement_rows_recovered_by_tolerance": rows_by_tol,
    "ambiguous_at_tol7": ambiguous,
    "examples_at_tol7": examples,
}, indent=2))
conn.close()
