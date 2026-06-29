"""Backfill EOD market-tide sentiment for every stored session.

Pure DB→DB reshape of market_tide_snapshots → market_tide_sentiment_daily (no
UW calls). Idempotent. Seed history so the EOD slope→forward-return backtest has
data to chew on.

Reproduce (force a full re-seed):
  uv run python scripts/backfill/market_tide_sentiment_backfill.py

One-off deploy seed (skip if already populated — used by macmini-prod.sh):
  uv run python scripts/backfill/market_tide_sentiment_backfill.py --if-empty
"""

from __future__ import annotations

import logging
import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.market_tide_sentiment import refresh_eod_sentiment

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_tide_sentiment_backfill")


def main(argv: list[str] | None = None) -> int:
    # --if-empty: one-off guard for the deploy hook — seed only when the table
    # has no rows yet, so re-running on every release is a no-op. Omit it (the
    # default) to force a full recompute, e.g. after a sentiment-formula change.
    if_empty = "--if-empty" in (sys.argv[1:] if argv is None else argv)

    settings = Settings.from_env()
    conn = psycopg.connect(settings.db_dsn())
    try:
        repo = Repository(conn, schema=settings.db_schema)
        if if_empty:
            existing = conn.execute(
                f"SELECT count(*) FROM {settings.db_schema}.market_tide_sentiment_daily"
            ).fetchone()[0]
            if existing:
                logger.info(
                    "--if-empty: %d row(s) already present — skip seed", existing
                )
                return 0
        # Cover the full stored corpus (YTD ≈ 121 sessions); sessions with no
        # bars are skipped inside the job.
        n = refresh_eod_sentiment(repo, sessions=300)
        logger.info("backfill complete: %d session(s) persisted", n)
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
