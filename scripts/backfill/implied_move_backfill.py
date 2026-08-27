"""Backfill nightly implied-move snapshots (spec §5-iii) over a date range.

    uv run python scripts/backfill/implied_move_backfill.py \
        --start 2025-12-26 --end 2026-08-26 [--execute]

Dry-run by default: prints per-date `prints_upcoming` counts (from the
calendar alone, same lookahead window `implied_move_snapshot` uses) without
touching the surface or persisting anything. Pass `--execute` to run the
real `implied_move_snapshot` per date and persist via
`ImpliedMoveRepository.upsert_rows`.

Mirrors `earnings_reactions_backfill.py`'s dry-run shape for the same
reason: `implied_move_snapshot` calls `upsert_rows`, which commits inside
its own cursor loop, so there is no transaction to roll back after the
fact — a dry-run that wants to show real numbers without writing has to
recompute them itself rather than call the writing function and undo it.
Rather than duplicate the covering-expiry/nearest-strike logic here, the
dry-run shows the cheap, honest number it CAN compute without touching the
grid (how many prints are in the window) and leaves `covered`/`not_covered`
at 0 with a `(dry-run)` suffix, exactly as the earnings-reactions backfill
does for its own `written`/`skipped_incomplete`.

Each `market_date` in the range is passed to `implied_move_snapshot` as
`as_of` so the covering-expiry pick replays POINT-IN-TIME: a backfilled
night sees only the surface + calendar rows that existed relative to that
night, never a later calendar entry that would leak information a real
nightly run on that date could not have had.

Per-date counts print unconditionally (executed or not) so an empty range is
VISIBLE as an explicit zero, matching `earnings_calendar_backfill.py`'s and
`earnings_reactions_backfill.py`'s convention. The surface
(`option_surface_grid_daily`) accrues 2025-12-26 -> present, so that is the
earliest date this backfill can produce a covered row from — Task 17's
seeding path for the industry desk starts here.
"""

from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, timedelta

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.earnings_calendar import EarningsCalendarRepository
from uw_scan.worker.jobs.implied_move_snapshot import (
    LOOKAHEAD_DAYS,
    implied_move_snapshot,
)

log = logging.getLogger("implied_move_backfill")


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
    totals = {"prints_upcoming": 0, "covered": 0, "not_covered": 0}

    with psycopg.connect(settings.db_dsn()) as conn:
        for d in _dates(args.start, args.end):
            if args.execute:
                result = implied_move_snapshot(conn, as_of=d, schema=settings.db_schema)
                suffix = (
                    f"covered={result['covered']:3d}  "
                    f"not_covered={result['not_covered']:3d}"
                )
            else:
                cal = EarningsCalendarRepository(conn, schema=settings.db_schema)
                horizon = d + timedelta(days=LOOKAHEAD_DAYS)
                prints_upcoming = len(
                    [
                        p
                        for p in cal.next_prints(on_or_after=d)
                        if p["report_date"] <= horizon
                    ]
                )
                result = {
                    "prints_upcoming": prints_upcoming,
                    "covered": 0,
                    "not_covered": 0,
                }
                suffix = "(dry-run)"

            for k in totals:
                totals[k] += result[k]
            print(f"{d}  prints_upcoming={result['prints_upcoming']:3d}  {suffix}")

    mode = "executed" if args.execute else "dry-run"
    print(
        f"{mode}: {totals['prints_upcoming']} prints upcoming, "
        f"{totals['covered']} covered, {totals['not_covered']} not covered"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
