"""One-shot single-name greek_exposure_daily backfill via UW's aggregate
/greek-exposure history (#179). UW-bound — gated behind --confirm. Idempotent
(upsert). The UW endpoint returns ~250 trailing days per call, so a single run
populates the full recent history; the nightly job then keeps it fresh.

This runs the SAME production job (greek_exposure_daily_refresh) immediately
rather than waiting for the 18:30 ET cron — no side-channel write path.

Reproduce:
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python \
      scripts/backfill/greek_exposure_daily_refresh_backfill.py --confirm
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.greek_exposure_daily_refresh import (
    greek_exposure_daily_refresh,
)

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("gex_daily_backfill")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument(
        "--tickers", default="", help="optional comma list; default = all single names"
    )
    args = ap.parse_args()

    settings = (
        Settings.from_env()
    )  # plain BaseModel: bare Settings() lacks required api_key
    if not args.confirm:
        logger.info("DRY RUN — pass --confirm to call UW. No requests made.")
        return 0

    keep = {t.strip().upper() for t in args.tickers.split(",") if t.strip()}
    ticker_filter = (lambda t: t.strip().upper() in keep) if keep else None

    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    try:
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            job_name="greek_exposure_daily_refresh_backfill",
        )
        summary = greek_exposure_daily_refresh(
            repo=repo, client=client, settings=settings, ticker_filter=ticker_filter
        )
        logger.info("backfill complete: %s", summary)
        return 0
    finally:
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
