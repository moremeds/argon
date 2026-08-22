#!/usr/bin/env python
"""One-off deep backfill for the rates market layer.

The scheduled job asks CFTC for 120 days, because these bytes are kept forever and every
run past the window re-reads history already stored.  This fills that history once.

It shares the job's core rather than reimplementing it -- same fetch, same artifact, same
availability rules -- so a fix to R1 or to the bulk-load detector cannot land in one path
and miss the other.  What it changes is one argument.

Supply needs no window argument at all: TreasuryDirect ignores date parameters and caps
every response at 250 rows, so the job's own per-``type`` requests already reach 2021 for
notes and 2012 for bonds.  Running this re-fetches them, which is free and idempotent --
identical bytes dedupe on ``content_hash`` and an already-stored vintage resolves as
unchanged.

Reproduce:

    uv run python scripts/backfill/macro_market_layer_backfill.py --start 2006-01-01
"""

from __future__ import annotations

import argparse
import logging
from datetime import date

from uw_scan.config import Settings
from uw_scan.worker.jobs.macro_market_layer_ingest import macro_market_layer_ingest_job

#: The CFTC TFF futures-only series begins here; asking earlier returns nothing extra.
TFF_HISTORY_START = date(2006, 1, 1)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--start",
        type=date.fromisoformat,
        default=TFF_HISTORY_START,
        help="earliest CFTC report date to request (default: 2006-01-01)",
    )
    args = parser.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s"
    )
    settings = Settings.from_env()
    result = macro_market_layer_ingest_job(
        dsn=settings.db_dsn(), positioning_start=args.start
    )
    print(
        f"status={result.status} feeds={result.feeds_succeeded}/{result.feeds_attempted} "
        f"created={result.observations_created} unchanged={result.observations_unchanged}"
    )
    if result.failed_feeds:
        print(f"failed={','.join(result.failed_feeds)}: {result.error_message}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
