"""Run the FIXED bucketing against the real production panel. Read-only.

Two arms from the same fixed code: a far-future cutoff reproduces the shipped
behaviour, today's date is the fix. If the arms agree, the fixture never
expressed the defect and the run proves nothing.
"""
from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.features import build_features
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.worker.jobs.fundamental_scoring import _build_buckets

TODAY = date(2026, 8, 23)
NEVER = date(2099, 1, 1)  # "no cutoff" — the shipped behaviour


def as_of(bucket):
    return max(d["knowledge_date"] for d in bucket.values())


s = Settings.from_env()
with psycopg.connect(s.db_dsn()) as conn:
    print(f"db = {s.db_name}  (read-only)")
    obs = FundamentalObsRepository(conn, schema="uw_scan")
    names = obs.list_universe("ranked")
    panel = obs.statement_panel(names)
    feats = build_features(panel)
    print(f"universe(ranked) = {len(names)}  panel tickers = {len(panel)}")

    old, w_old = _build_buckets(feats, panel, knowledge_cutoff=NEVER)
    new, w_new = _build_buckets(feats, panel, knowledge_cutoff=TODAY)

    print(f"\nwithheld  no-cutoff={w_old}   cutoff={TODAY}: {w_new}")

    latest = max(old)
    print(f"\nlatest bucket = {latest}")
    print(f"  ARM A (no cutoff, = shipped): as_of={as_of(old[latest])}  names={len(old[latest])}")
    if latest in new:
        print(f"  ARM B (cutoff today, = fix): as_of={as_of(new[latest])}  names={len(new[latest])}")
    else:
        print("  ARM B: bucket empty after withholding")

    dropped = set(old[latest]) - set(new.get(latest, {}))
    print(f"  names withheld from {latest}: {sorted(dropped)}")
    for t in sorted(dropped):
        d = old[latest][t]
        print(f"    {t}: period={d['period'][:10]} knowledge={d['knowledge_date']} "
              f"filing_date_known={d['filing_date_known']}")

    fut = {t: d["knowledge_date"] for b in old.values() for t, d in b.items()
           if d["knowledge_date"] > TODAY}
    print(f"\nevery unarrived row across ALL buckets: {fut}")

    # What the read path currently serves, for contrast.
    cur = conn.execute(
        "select max(as_of), count(*) from uw_scan.fundamental_scores where as_of > current_date"
    ).fetchone()
    print(f"\npersisted future-dated rows still in the table: max_as_of={cur[0]} rows={cur[1]}")
