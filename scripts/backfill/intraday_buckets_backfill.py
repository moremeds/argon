"""One-shot backfill for option_intraday_buckets tickers missed by the #180
shard bug (primary-only job wrongly shard-filtered). UW-bound — gated behind
--confirm so it never runs by accident, and bounded by UW's ~22-calendar-day
intraday retention (older sessions return empty buckets, not an error).

option_intraday_buckets has no ticker/underlying column (only option_symbol),
so the "already-covered" set cannot be computed from the table without OCC
parsing — we don't guess. Instead the operator passes the known-missed set
explicitly (the 6 mega-caps + any others), or --all to re-run the full
watchlist (idempotent, but costs more UW). The job's advisory lock + upsert
make every path safe to re-run.

Reproduce (missed set):
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python scripts/backfill/intraday_buckets_backfill.py \
      --tickers TSLA,NVDA,MSFT,GOOGL,META,AVGO --confirm
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_intraday_jobs import refresh_intraday_for_top_oi_movers

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("intraday_backfill")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument(
        "--tickers", default="", help="comma list of underlyings to backfill"
    )
    ap.add_argument(
        "--all", action="store_true", help="backfill the full active watchlist"
    )
    args = ap.parse_args()

    settings = (
        Settings.from_env()
    )  # plain BaseModel: bare Settings() lacks required api_key
    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    try:
        if args.all:
            target = {c.ticker.upper() for c in repo.list_watchlist_cards()}
        else:
            target = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
        if not target:
            logger.error("no tickers: pass --tickers T1,T2 or --all")
            return 2
        if not args.confirm:
            logger.info(
                "DRY RUN — would backfill %d tickers: %s", len(target), sorted(target)
            )
            return 0

        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            job_name="intraday_buckets_backfill",
        )
        summary = refresh_intraday_for_top_oi_movers(
            repo=repo,
            client=client,
            settings=settings,
            ticker_filter=lambda t: t.strip().upper() in target,
        )
        logger.info("backfill complete: %s", summary)
        return 0
    finally:
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
