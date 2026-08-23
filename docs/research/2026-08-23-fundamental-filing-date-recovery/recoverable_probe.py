"""How many NULL filing dates would a re-pull recover TODAY?

Targets the tickers UW DOES date (>=1 dated period) but where we still hold NULLs.
The earlier probe sampled the most-NULL tickers, which selected the cohort UW
never dates at all -- that is why it found 0 and this one will not.
"""
import json
import httpx, psycopg
from uw_scan.config import Settings

s = Settings.from_env()
h = {"Authorization": f"Bearer {s.api_key.get_secret_value()}", "Accept": "application/json"}
B = "https://api.unusualwhales.com"

with psycopg.connect(s.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute(f"""
        SELECT ticker
          FROM {s.db_schema}.fundamental_statement_obs
         WHERE period_type='quarterly' AND period_end >= date '2025-01-01'
      GROUP BY ticker
        HAVING count(*) FILTER (WHERE filing_published_at IS NOT NULL) > 0
           AND count(*) FILTER (WHERE filing_published_at IS NULL) > 0
      ORDER BY ticker
    """)
    cand = [r[0] for r in cur.fetchall()]
    print(f"TICKERS_PARTIALLY_DATED={len(cand)}", flush=True)

    checked = recoverable = 0
    rows_recoverable = 0
    hits = []
    with httpx.Client(timeout=30.0) as c:
        for t in cand:
            r = c.get(f"{B}/api/stock/{t}/fundamental-breakdown", headers=h)
            if r.status_code != 200:
                continue
            uw = {}
            for row in (r.json().get("data") or {}).get("general") or []:
                pe, fd = row.get("report_period_end_date"), row.get("filing_date")
                if pe and fd:
                    uw[str(pe)[:10]] = str(fd)[:10]
            cur.execute(f"""
                SELECT period_end, count(*)
                  FROM {s.db_schema}.fundamental_statement_obs
                 WHERE ticker=%s AND period_type='quarterly'
                   AND filing_published_at IS NULL AND period_end >= date '2025-01-01'
              GROUP BY period_end ORDER BY period_end
            """, (t,))
            for pe, n in cur.fetchall():
                checked += 1
                if pe.isoformat() in uw:
                    recoverable += 1
                    rows_recoverable += n
                    hits.append((t, pe.isoformat(), uw[pe.isoformat()], n))

print(json.dumps({
    "null_periods_checked": checked,
    "periods_uw_can_now_date": recoverable,
    "statement_rows_recoverable": rows_recoverable,
    "sample": hits[:25],
}, indent=2))
