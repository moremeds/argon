"""Does UW now supply a filing_date for periods our panel holds as NULL?

If yes, the ON CONFLICT clause in record_statements (which updates only
last_seen_at) has been discarding them, and every re-ingest keeps discarding.

Reproduce: cat stuck_null_probe.py | docker exec -i argon-worker-uw-0-1 python - <N_TICKERS>
"""
import json
import sys
from datetime import date, datetime

import httpx
import psycopg
from uw_scan.config import Settings

N = int(sys.argv[1]) if len(sys.argv) > 1 else 30
settings = Settings.from_env()
hdrs = {"Authorization": f"Bearer {settings.api_key.get_secret_value()}",
        "Accept": "application/json"}

with psycopg.connect(settings.db_dsn()) as conn, conn.cursor() as cur:
    cur.execute(f"""
        SELECT ticker,
               count(*) FILTER (WHERE filing_published_at IS NULL) AS nulls,
               count(*) AS total
          FROM {settings.db_schema}.fundamental_statement_obs
         WHERE period_type='quarterly' AND period_end >= date '2024-01-01'
      GROUP BY ticker
        HAVING count(*) FILTER (WHERE filing_published_at IS NULL) > 0
      ORDER BY 2 DESC
         LIMIT %s
    """, (N,))
    cand = cur.fetchall()
    print(f"TICKERS_WITH_NULLS_SAMPLED={len(cand)}", flush=True)

    recoverable = 0
    checked = 0
    detail = []
    with httpx.Client(timeout=30.0) as c:
        for ticker, nulls, total in cand:
            r = c.get(f"https://api.unusualwhales.com/api/stock/{ticker}/fundamental-breakdown",
                      headers=hdrs)
            if r.status_code != 200:
                detail.append({"ticker": ticker, "http": r.status_code})
                continue
            general = (r.json().get("data") or {}).get("general") or []
            uw_dates = {}
            for row in general:
                pe, fd = row.get("report_period_end_date"), row.get("filing_date")
                if pe and fd:
                    uw_dates[str(pe)[:10]] = str(fd)[:10]
            cur.execute(f"""
                SELECT DISTINCT period_end
                  FROM {settings.db_schema}.fundamental_statement_obs
                 WHERE ticker=%s AND period_type='quarterly'
                   AND filing_published_at IS NULL AND period_end >= date '2024-01-01'
            """, (ticker,))
            null_periods = [r[0].isoformat() for r in cur.fetchall()]
            checked += len(null_periods)
            hits = [p for p in null_periods if p in uw_dates]
            recoverable += len(hits)
            detail.append({"ticker": ticker, "null_periods": len(null_periods),
                           "uw_has_date_for": len(hits),
                           "sample": [(p, uw_dates[p]) for p in hits[:3]]})

print(json.dumps({"null_periods_checked": checked,
                  "uw_supplies_a_date_now": recoverable,
                  "detail": detail}, indent=2))
