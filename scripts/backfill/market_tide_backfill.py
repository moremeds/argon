"""One-shot market-tide backfill via UW /market/market-tide (date param).

UW returns the full 5-min series for one session per call and supports a ~30
trading-day lookback, so this walks back over weekdays calling the SAME
production scanner (capture_spot=False — a live spot is meaningless against a
past bar) until it has filled `--sessions` sessions with data. Idempotent
(upsert). UW-bound — gated behind --confirm. Holidays return no data and are
skipped automatically.

Reproduce:
  UW_SCAN_ALLOW_DB_MISMATCH=1 uv run python \
      scripts/backfill/market_tide_backfill.py --confirm --sessions 30
"""

from __future__ import annotations

import argparse
import logging
from datetime import date, timedelta

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.scanners import market_tide as market_tide_scanner
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.storage.repository import Repository

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("market_tide_backfill")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--confirm", action="store_true", help="actually call UW")
    ap.add_argument(
        "--sessions", type=int, default=30, help="target sessions to fill (UW caps ~30)"
    )
    ap.add_argument(
        "--max-calendar-days",
        type=int,
        default=60,
        help="safety cap on how far back to walk",
    )
    args = ap.parse_args()

    settings = Settings.from_env()
    if not args.confirm:
        logger.info("DRY RUN — pass --confirm to call UW. No requests made.")
        return 0

    repo = Repository(psycopg.connect(settings.db_dsn()), schema=settings.db_schema)
    # Route through the telemetry recorder so backfill UW spend is visible to the
    # budget governor (research pool) — Phase 0 of the UW budget rework.
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    filled = 0
    attempted = 0
    try:
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            telemetry_recorder=recorder,
            job_name="market_tide_backfill",
        )
        d = date.today()
        while filled < args.sessions and attempted < args.max_calendar_days:
            if d.weekday() < 5:  # skip weekends; holidays self-skip via 400→empty
                attempted += 1
                n = market_tide_scanner.run(
                    client,
                    repo,
                    spot_ticker=settings.market_tide_spot_ticker,
                    trading_date=d,
                    capture_spot=False,
                )
                if n > 0:
                    filled += 1
                    logger.info(
                        "backfilled %s — %d bars (%d/%d)", d, n, filled, args.sessions
                    )
                else:
                    logger.info("no data %s (holiday or unpublished)", d)
            d -= timedelta(days=1)
        logger.info(
            "backfill complete: %d sessions filled, %d weekdays attempted",
            filled,
            attempted,
        )
        return 0
    finally:
        recorder.close()
        repo.conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
