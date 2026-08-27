"""Backfill/seed the durable earnings calendar (spec §5-i) from UW's classified slots.

    uv run python scripts/backfill/earnings_calendar_backfill.py \
        --start 2026-08-01 --end 2026-08-25 [--execute]

Dry-run by default: fetches and prints per-date listing counts without writing to the
DB. Pass `--execute` to persist via `EarningsCalendarRepository.upsert_rows`.

This is BOTH the historical-calendar recovery path (the endpoint takes a `date` param;
UW's recent-history retrievability is verified in
`docs/research/2026-08-23-fundamental-filing-date-recovery/VERDICT.md`) and Task 17's
local seeding path for a fresh DB — never grab this via a `/tmp` one-off.

Per-date counts print unconditionally, executed or not, so a date range UW no longer
serves is VISIBLE as an explicit zero rather than a silent gap (see the module
docstring in `sources/earnings_calendar.py` on why a single-page read already made this
mistake once).

Cost: 2 slots x up to `MAX_PAGES` pages per date — the same call shape the daily job
pays for one date at a time.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.sources.earnings_calendar import fetch_calendar_listings
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder

log = logging.getLogger("earnings_calendar_backfill")


def _dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument(
        "--execute",
        action="store_true",
        help="write rows (default: dry-run, fetch and print only)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    if args.end < args.start:
        log.error("--end %s precedes --start %s", args.end, args.start)
        return 1

    settings = Settings.from_env()
    recorder = ExternalApiRequestRecorder(settings.db_dsn(), schema=settings.db_schema)
    total_listed = 0
    total_written = 0
    try:
        client = UwClient(
            api_key=settings.api_key.get_secret_value(),
            base_url=settings.base_url,
            timeout=settings.request_timeout_seconds,
            telemetry_recorder=recorder,
            job_name="earnings_calendar_backfill",
        )
        with psycopg.connect(settings.db_dsn()) as conn:
            repo = EarningsCalendarRepository(conn, schema=settings.db_schema)
            for d in _dates(args.start, args.end):
                listings = fetch_calendar_listings(client, d)
                written = 0
                if args.execute and listings:
                    written = repo.upsert_rows(
                        [
                            {
                                "ticker": listing.symbol,
                                "report_date": d,
                                "session": listing.session,
                                "source": "uw_calendar",
                            }
                            for listing in listings
                        ]
                    )
                total_listed += len(listings)
                total_written += written
                suffix = f"written={written:4d}" if args.execute else "(dry-run)"
                print(f"{d}  listed={len(listings):4d}  {suffix}")
    finally:
        recorder.close()

    mode = "executed" if args.execute else "dry-run"
    print(f"{mode}: {total_listed} listings seen, {total_written} new rows written")
    return 0


if __name__ == "__main__":
    sys.exit(main())
