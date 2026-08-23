"""Measure: for a name that REPORTS on day D, when does the statement become retrievable?

Two questions, deliberately separated:
  M1  filing lag   -- for the period matched to that report, filing_published_at - D
  M2  period land  -- did the reported period appear in our panel at all

M1 sizes the retry window for names UW dates. M2 sizes the tail UW never dates.
The earlier 21-day probe took max(filing_published_at) PER TICKER, which returned an
old period whenever the new one was undated -- that is what produced -1269 day "lags".
This one matches the specific period: greatest period_end <= report_date.

Reproduce:  cat lag_probe.py | docker exec -i argon-worker-uw-0-1 python - <DAYS>
"""
import json
import sys
from collections import Counter
from datetime import date, timedelta

from uw_scan.config import Settings
import httpx
import psycopg

DAYS = int(sys.argv[1]) if len(sys.argv) > 1 else 90
TODAY = date.today()

settings = Settings.from_env()
calendar: dict[str, list[str]] = {}   # ticker -> [report_date, ...]
calls = 0
errors = []

base = "https://api.unusualwhales.com"
hdrs = {"Authorization": f"Bearer {settings.api_key.get_secret_value()}",
        "Accept": "application/json"}
with httpx.Client(timeout=30.0) as uw:
    for i in range(DAYS):
        d = (TODAY - timedelta(days=i)).isoformat()
        for slot in ("premarket", "afterhours"):
            page = 0
            while page < 3:
                r = uw.get(
                    f"{base}/api/earnings/{slot}",
                    params={"date": d, "limit": 100, "page": page},
                    headers=hdrs,
                )
                calls += 1
                if r.status_code != 200:
                    errors.append((d, slot, r.status_code))
                    break
                rows = r.json().get("data") or []
                for row in rows:
                    sym = row.get("symbol")
                    rd = row.get("report_date") or d
                    if sym:
                        calendar.setdefault(sym, []).append(rd)
                if len(rows) < 100:
                    break
                page += 1

print(f"CALLS={calls} ERRORS={len(errors)} TICKERS_ON_CALENDAR={len(calendar)}", flush=True)

dsn = settings.db_dsn()
out = {"days": DAYS, "today": TODAY.isoformat(), "calls": calls,
       "calendar_tickers": len(calendar), "rows": []}

with psycopg.connect(dsn) as conn, conn.cursor() as cur:
    cur.execute(f"SELECT ticker FROM {settings.db_schema}.fundamental_universe WHERE tier='ranked'")
    universe = {r[0] for r in cur.fetchall()}
    hits = sorted(set(calendar) & universe)
    print(f"IN_UNIVERSE={len(hits)}", flush=True)

    for t in hits:
        for rd in sorted(set(calendar[t])):
            cur.execute(
                f"""
                SELECT period_end, filing_published_at
                  FROM {settings.db_schema}.fundamental_statement_obs
                 WHERE ticker = %s AND period_type = 'quarterly'
                   AND period_end <= %s::date
              ORDER BY period_end DESC
                 LIMIT 1
                """,
                (t, rd),
            )
            row = cur.fetchone()
            pe, fp = (row[0], row[1]) if row else (None, None)
            out["rows"].append({
                "ticker": t,
                "report_date": rd,
                "period_end": pe.isoformat() if pe else None,
                "filing_published_at": fp.isoformat() if fp else None,
                "period_gap_days": (date.fromisoformat(rd) - pe).days if pe else None,
                "filing_lag_days": (fp - date.fromisoformat(rd)).days if fp else None,
            })

lags = sorted(r["filing_lag_days"] for r in out["rows"] if r["filing_lag_days"] is not None)
n_total = len(out["rows"])
n_dated = len(lags)


def pct(xs, p):
    if not xs:
        return None
    return xs[min(len(xs) - 1, int(round(p * (len(xs) - 1))))]


out["summary"] = {
    "report_events": n_total,
    "dated": n_dated,
    "undated": n_total - n_dated,
    "lag_min": lags[0] if lags else None,
    "lag_p50": pct(lags, 0.50),
    "lag_p90": pct(lags, 0.90),
    "lag_p95": pct(lags, 0.95),
    "lag_p99": pct(lags, 0.99),
    "lag_max": lags[-1] if lags else None,
    "lag_le_0": sum(1 for x in lags if x <= 0),
    "lag_le_3": sum(1 for x in lags if x <= 3),
    "lag_le_7": sum(1 for x in lags if x <= 7),
    "lag_le_14": sum(1 for x in lags if x <= 14),
    "lag_le_21": sum(1 for x in lags if x <= 21),
    "lag_le_30": sum(1 for x in lags if x <= 30),
    "negative_lags": sum(1 for x in lags if x < 0),
    "period_gap_p50": pct(sorted(r["period_gap_days"] for r in out["rows"] if r["period_gap_days"] is not None), 0.5),
}
out["lag_histogram"] = dict(sorted(Counter(lags).items()))
print(json.dumps(out["summary"], indent=2), flush=True)
with open("/tmp/lag_probe.json", "w") as fh:
    json.dump(out, fh, indent=2)
print("WROTE /tmp/lag_probe.json", flush=True)
