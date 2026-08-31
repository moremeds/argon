"""Run (or preview) the nightly desk matrix rollup once (Task 12, Task 17's
seeding path -- no /tmp one-offs).

    uv run python scripts/backfill/fundamentals_desk_rollup_run.py [--execute]

Dry-run by default: `fundamentals_desk_rollup`'s own `dry_run` flag computes
every (ticker, period_end) row exactly as a real run would and skips only the
final `upsert_rows` write, so the printed counts are real, not an estimate.
Pass --execute to persist.

There is no `--as-of` here, unlike the delta-rail runner -- this job always
reads the LATEST accepted-version statement panel; there is no point-in-time
replay question to guard against.
"""

from __future__ import annotations

import argparse
import logging
import sys

import psycopg

from uw_scan.config import Settings
from uw_scan.worker.jobs.fundamentals_desk_rollup import fundamentals_desk_rollup

log = logging.getLogger("fundamentals_desk_rollup_run")


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument(
        "--execute",
        action="store_true",
        help="write rows (default: dry-run, compute and print counts only)",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )

    settings = Settings.from_env()
    with psycopg.connect(settings.db_dsn()) as conn:
        result = fundamentals_desk_rollup(
            conn, schema=settings.db_schema, dry_run=not args.execute
        )

    mode = "executed" if args.execute else "dry-run"
    print(
        f"{mode}: tickers={result['tickers']} rows={result['rows']} "
        f"written={result['written']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
