"""Anti-fabrication, stated precisely per table.

options_volume_daily and uw_positioning measured ZERO across 2026-08-11..14 before
the heal, so a date-range check is valid for them. short_interest_snapshots had 170
rows dated 08-14 already (provider-supplied snapshot_at, written by the Sunday live
scan), so only run-attribution answers the question there.
"""
import psycopg
from uw_scan.config import Settings
s = Settings.from_env()
conn = psycopg.connect(s.db_dsn())
with conn.cursor() as cur:
    print("=== ANTI-FABRICATION ===")
    for t, c in [("options_volume_daily", "trade_date"), ("uw_positioning", "snapshot_date")]:
        cur.execute(f"SELECT count(*) FROM uw_scan.{t} WHERE {c} BETWEEN '2026-08-11' AND '2026-08-14'")
        n = cur.fetchone()[0]
        print(f"  {'OK ' if n == 0 else 'FABRICATION!'} {t:<28} rows in outage window = {n}  (baseline 0)")

    cur.execute("""SELECT count(*) FROM uw_scan.short_interest_snapshots si
                   JOIN uw_scan.scan_runs r ON r.run_id = si.run_id
                   WHERE r.notes IN ('pipeline_replay','flow_chain_replay')""")
    n = cur.fetchone()[0]
    print(f"  {'OK ' if n == 0 else 'FABRICATION!'} {'short_interest_snapshots':<28} rows from a replay run = {n}")

    cur.execute("""SELECT count(*), count(DISTINCT ticker) FROM uw_scan.scan_runs
                   WHERE notes IN ('pipeline_replay','flow_chain_replay')""")
    runs, tk = cur.fetchone()
    print(f"\nreplay scan_runs: {runs} across {tk} tickers")
    cur.execute("SELECT count(*) FROM uw_scan.data_gap_items WHERE run_id >= 84 AND status='healed'")
    print("items healed today:", cur.fetchone()[0])
    cur.execute("SELECT max(daily_req_count) FROM uw_scan.api_request_audit WHERE request_started_at>=CURRENT_DATE")
    print("UW spent today:", cur.fetchone()[0], "/ 120000")
