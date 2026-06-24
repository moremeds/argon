"""One-shot backfill: re-derive vrp_daily (+ stock_analytics_daily) for the
active watchlist by invoking the fixed nightly vol-analytics rollup once.

Recovers the 2026-05-22+ vrp_daily freeze: UW's realized_volatility column went
null, which made vrp = iv - rv NaN, so persist_vrp_daily wrote nothing for ~90%
of the watchlist. The rollup now fills RV from the fresh price column
(_fill_rv_from_price). This runner just calls the rollup — it reads
realized_volatility_history + SPY OHLC from the DB and upserts vrp_daily.

Pure DB->DB: ZERO UW/massive calls. Idempotent (upserts) — safe to re-run, and
the nightly 18:00 ET cron will keep it fresh going forward.

Reproduce (targets whatever .env.local points at — for the mini that is
100.66.147.98/option_wizard, the allowed prodlike combo):
  cd /Users/chenxi/projects/argon
  set -a; source .env.local; set +a
  uv run python scripts/backfill_vrp_daily.py
"""

from __future__ import annotations

import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.volatility_jobs import nightly_vol_analytics_rollup

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        nightly_vol_analytics_rollup(repo=repo)


if __name__ == "__main__":
    main()
