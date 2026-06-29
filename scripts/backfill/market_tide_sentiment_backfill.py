"""Backfill EOD market-tide sentiment for every stored session.

Pure DB→DB reshape of market_tide_snapshots → market_tide_sentiment_daily (no
UW calls). Idempotent. Seed history so the EOD slope→forward-return backtest has
data to chew on.

Reproduce:
  uv run python scripts/backfill/market_tide_sentiment_backfill.py
"""

from __future__ import annotations

import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.market_tide_sentiment import refresh_eod_sentiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_tide_sentiment_backfill")


def main() -> int:
    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    try:
        repo = Repository(conn, schema=settings.db_schema)
        # Cover the full stored corpus (YTD ≈ 121 sessions); sessions with no
        # bars are skipped inside the job.
        n = refresh_eod_sentiment(repo, sessions=300)
        logger.info("backfill complete: %d session(s) persisted", n)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
