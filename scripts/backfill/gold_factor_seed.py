"""One-time seed of the gold factor model's history, then one compute.

    uv run python scripts/backfill/gold_factor_seed.py

1. IB 1-day MIDPOINT closes (XAUUSD + the six dollar-index pairs) through xenon
   POST /historical/bars -> macro_series_daily, source 'IB'. One call of 17 Y or more outruns
   IB's 60 s timeout, and IB's "6 Y" is not an exact calendar span, so the history comes in
   overlapping 6 Y windows plus a final 2 Y to now; repeated dates are identical and the
   latest vintage wins on read. XAUUSD starts 2010-06-09 at IB, which bounds the model.
2. FRED DFII10 / DGS10 from 2010 through the real gold_fred_ingest_job (argon's stored FRED
   history starts 2021-05).
3. gold_factor_compute_job.

Needs XENON_QUERY_API_URL / XENON_QUERY_API_KEY. Idempotent: inserts are ON CONFLICT DO
NOTHING on (series_id, obs_date, as_of) and the compute upserts. Parity of these xenon closes
with the study: the "xenon" block of docs/research/2026-10-10-gold-factor-parity.json.
"""

from __future__ import annotations

from datetime import date

import psycopg

from uw_scan.config import Settings
from uw_scan.worker.jobs.gold_factor import fetch_ib_legs, gold_factor_compute_job
from uw_scan.worker.jobs.gold_jobs import gold_fred_ingest_job

# (duration, end) per window, oldest first; each 6 Y window overlaps the next by a year.
WINDOWS = [
    ("6 Y", "20150201-00:00:00"),
    ("6 Y", "20200201-00:00:00"),
    ("6 Y", "20250201-00:00:00"),
    ("2 Y", ""),
]
FRED_START = date(2010, 1, 1)


def main() -> None:
    s = Settings.from_env()
    if not (s.xenon_query_api_url and s.xenon_query_api_key):
        raise SystemExit("XENON_QUERY_API_URL and XENON_QUERY_API_KEY must be set")
    dsn = s.db_dsn()
    with psycopg.connect(dsn) as conn:
        for duration, end in WINDOWS:
            failures = fetch_ib_legs(
                conn,
                base_url=s.xenon_query_api_url,
                api_key=s.xenon_query_api_key.get_secret_value(),
                duration=duration,
                end_date_time=end,
            )
            print(f"{duration} to {end or 'now'}: {'ok' if not failures else failures}")
            if failures:
                raise SystemExit("xenon fetch failed; rerun (inserts are idempotent)")
    gold_fred_ingest_job(
        dsn=dsn,
        series_ids=["DFII10", "DGS10"],
        lookback_days=(date.today() - FRED_START).days,
    )
    print(f"gold_factor_daily: {gold_factor_compute_job(dsn=dsn)} rows")


if __name__ == "__main__":
    main()
