"""One-shot SPY OHLC seed for Volatility Tab v2.

Pulls ~3 years of daily SPY bars from massive.com and upserts into
`uw_scan.index_ohlc_daily`. Re-runnable; idempotent.

Usage:
    uv run python scripts/seed_spy_ohlc.py [--years 3] [--ticker SPY]
"""

from __future__ import annotations

import argparse
import logging
import sys
from contextlib import closing
from datetime import date, timedelta

import psycopg

from uw_scan.config import Settings
from uw_scan.sources.ohlc import MassiveOhlcProvider
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
log = logging.getLogger("seed_spy_ohlc")


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--years", type=int, default=3)
    parser.add_argument("--ticker", default="SPY")
    args = parser.parse_args()

    settings = Settings.from_env()
    if settings.massive_api_key is None:
        log.error("MASSIVE_API_KEY env var not set")
        return 1
    api_key = settings.massive_api_key.get_secret_value()

    end = date.today()
    start = end - timedelta(days=args.years * 365)
    log.info("Fetching %s daily bars %s → %s", args.ticker, start, end)

    with MassiveOhlcProvider(
        api_key=api_key,
        base_url=settings.massive_base_url,
    ) as prov:
        bars = prov.fetch_daily(args.ticker, start=start, end=end)
    log.info("Fetched %d bars", len(bars))

    with closing(psycopg.connect(settings.db_dsn())) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        n = repo.upsert_index_ohlc_rows(bars)
        conn.commit()
    log.info("Upserted %d rows into index_ohlc_daily", n)
    return 0


if __name__ == "__main__":
    sys.exit(main())
