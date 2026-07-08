"""One-off/manual technical_daily refresh over the watchlist (or --tickers).

Reproduce: uv run python scripts/backfill/technicals_refresh_backfill.py [--tickers NVDA,SPY]
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.technical_daily_refresh import technical_daily_refresh

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--tickers", default=None, help="comma-separated subset")
    args = parser.parse_args()
    settings = Settings.from_env()
    ticker_filter = args.tickers.split(",") if args.tickers else None
    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        summary = technical_daily_refresh(
            repo=repo, settings=settings, ticker_filter=ticker_filter
        )
    print(summary)


if __name__ == "__main__":
    main()
