"""Backfill earnings reaction history (spec §5-ii) from calendar x daily_ohlc.

    uv run python scripts/backfill/earnings_reactions_backfill.py \
        --start 2025-12-01 --end 2026-08-25 [--execute]

Dry-run by default: computes and prints per-date written/skipped counts
without persisting. Pass `--execute` to write via
`EarningsReactionsRepository.upsert_rows` (through `earnings_reactions_compute`).

Two-source date range, no duplicate logic
------------------------------------------
The durable `earnings_calendar` (migration 144) only accrues forward from
whenever the nightly ingest started writing to it — history predating that
has no calendar row, so a print from before then would never surface to
`earnings_reactions_compute` no matter how far back `daily_ohlc` goes. This
script closes that gap by seeding calendar rows for periods
`fundamental_statement_obs.filing_published_at` already knows about (source
`statement_obs`, `session=NULL` — the same "resolved to a date, unresolved to
a session" shape `fundamental_ingest_daily.persist_unknown_statements` uses,
see `earnings_calendar.py`'s module docstring on why NULL never clobbers a
later-known session). It then runs the SAME `earnings_reactions_compute` core
the nightly job uses, one day at a time over the requested range, so there is
exactly one code path from calendar row to reaction row regardless of which
of the two sources produced the calendar row.

Per-date counts print unconditionally (executed or not) so an empty range is
VISIBLE as an explicit zero, matching `earnings_calendar_backfill.py`'s
convention.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.worker.jobs.earnings_reactions import earnings_reactions_compute

log = logging.getLogger("earnings_reactions_backfill")


def _dates(start: date, end: date):
    d = start
    while d <= end:
        yield d
        d += timedelta(days=1)


def _seed_calendar_from_statement_obs(
    conn: psycopg.Connection, schema: str, start: date, end: date, *, execute: bool
) -> tuple[int, int]:
    """Insert calendar rows (source='statement_obs', session=NULL) for every
    distinct (ticker, filing_published_at) in range. Returns
    (candidate_pairs_seen, genuinely_new_rows_written) — the second element is
    always 0 in dry-run (nothing is written), but the first is real either way
    so a dry-run still shows how many candidates the range holds."""
    with conn.cursor() as cur:
        cur.execute(
            f"""SELECT DISTINCT ticker, filing_published_at
                  FROM {schema}.fundamental_statement_obs
                 WHERE filing_published_at IS NOT NULL
                   AND filing_published_at BETWEEN %s AND %s""",
            (start, end),
        )
        pairs = cur.fetchall()
    if not execute or not pairs:
        return len(pairs), 0
    cal = EarningsCalendarRepository(conn, schema=schema)
    written = cal.upsert_rows(
        [
            {
                "ticker": ticker,
                "report_date": filing_date,
                "session": None,
                "source": "statement_obs",
            }
            for ticker, filing_date in pairs
        ]
    )
    return len(pairs), written


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start", required=True, type=date.fromisoformat)
    ap.add_argument("--end", required=True, type=date.fromisoformat)
    ap.add_argument(
        "--execute",
        action="store_true",
        help="write rows (default: dry-run, compute and print only)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    if args.end < args.start:
        log.error("--end %s precedes --start %s", args.end, args.start)
        return 1

    settings = Settings.from_env()
    total_prints = 0
    total_written = 0
    total_skipped = 0

    with psycopg.connect(settings.db_dsn()) as conn:
        candidates, seeded = _seed_calendar_from_statement_obs(
            conn, settings.db_schema, args.start, args.end, execute=args.execute
        )
        print(
            f"statement_obs calendar seed: {candidates} candidate print(s), "
            f"{seeded} new row(s)"
        )

        for d in _dates(args.start, args.end):
            if args.execute:
                result = earnings_reactions_compute(
                    conn,
                    as_of=d,
                    lookback_days=0,
                    schema=settings.db_schema,
                )
            else:
                cal = EarningsCalendarRepository(conn, schema=settings.db_schema)
                result = {
                    "prints": len(cal.prints_between(d, d)),
                    "written": 0,
                    "skipped_incomplete": 0,
                }
            total_prints += result["prints"]
            total_written += result["written"]
            total_skipped += result["skipped_incomplete"]
            suffix = (
                f"written={result['written']:3d} skipped={result['skipped_incomplete']:3d}"
                if args.execute
                else "(dry-run)"
            )
            print(f"{d}  prints={result['prints']:3d}  {suffix}")

    mode = "executed" if args.execute else "dry-run"
    print(
        f"{mode}: {total_prints} prints seen, {total_written} reactions written, "
        f"{total_skipped} skipped (no close yet)"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
