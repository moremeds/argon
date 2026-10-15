"""One-time seed of the gold factor model's FRED history, then one compute.

    uv run python scripts/backfill/gold_factor_seed.py

1. FRED DFII10 / DGS10 from 2010 through the real gold_fred_ingest_job (argon's stored FRED
   history starts 2021-05).
2. gold_factor_compute_job, which reads XAUUSD and the six dollar-index pairs (IB 1-day MIDPOINT
   closes) from the livewire lake under MARKET_WAREHOUSE_LAKE. XAUUSD starts 2010-06-09 at IB,
   which bounds the model.

Idempotent: FRED inserts are ON CONFLICT DO NOTHING and the compute upserts.
"""

from __future__ import annotations

from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.gold_factor import gold_factor_compute_job
from uw_scan.worker.jobs.gold_jobs import gold_fred_ingest_job

FRED_START = date(2010, 1, 1)


def main() -> None:
    s = Settings.from_env()
    dsn = s.db_dsn()
    gold_fred_ingest_job(
        dsn=dsn,
        series_ids=["DFII10", "DGS10"],
        lookback_days=(date.today() - FRED_START).days,
    )
    n = gold_factor_compute_job(dsn=dsn, lake_root=s.market_warehouse_lake_root)
    print(f"gold_factor_daily: {n} rows")


if __name__ == "__main__":
    main()
