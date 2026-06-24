"""One-time backfill for option_surface_grid_daily.

Fills per-strike IV/greeks for recent weekdays not yet captured.
UW returns 403 beyond ~30 trading days so run this promptly after first deploy.

Run: uv run python scripts/option_surface_backfill.py [--days-back 30]
"""

from __future__ import annotations

import argparse
import logging

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.repository import Repository
from uw_scan.worker.jobs.option_surface_capture import option_surface_backfill


def main() -> None:
    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s"
    )
    log = logging.getLogger(__name__)

    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument(
        "--days-back",
        type=int,
        default=30,
        help="trading days to look back (default 30)",
    )
    p.add_argument(
        "--end-date",
        type=lambda s: __import__("datetime").date.fromisoformat(s),
        default=None,
        metavar="YYYY-MM-DD",
        help="stop after this date (inclusive); useful to preserve daily UW quota",
    )
    p.add_argument(
        "--quota-limit",
        type=int,
        default=None,
        metavar="N",
        help="stop when UW daily request count reaches N (e.g. 20000)",
    )
    args = p.parse_args()

    settings = Settings.from_env()
    log.info(
        "host=%s db=%s schema=%s days_back=%d",
        settings.db_host,
        settings.db_name,
        settings.db_schema,
        args.days_back,
    )

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = Repository(conn, schema=settings.db_schema)
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            job_name="option_surface_backfill",
        )
        n = option_surface_backfill(
            repo=repo,
            client=client,
            days_back=args.days_back,
            end_date=args.end_date,
            quota_limit=args.quota_limit,
        )

    log.info("done: %d rows written", n)


if __name__ == "__main__":
    main()
