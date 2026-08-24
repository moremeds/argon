"""Classify availability evidence for stored statement versions (migration 130).

    uv run python scripts/backfill/fundamental_observation_availability.py
        [--tickers NVDA,MSFT] [--batch-size 5000] [--max-batches N] [--counts]

Entry point for `worker/jobs/fundamental_observation_availability.py`. The job
holds all the logic — this script only builds the connection, so a manual run and
any future scheduled run cannot drift apart.

Cost: ZERO provider calls. It reads rows Argon already holds and writes derived
claims, so it is not on the UW budget and can be run at any hour. It is safe to
re-run: every claim is written under a deterministic key with ON CONFLICT DO
NOTHING, so a second pass over covered ground inserts nothing.

It issues `current_vintage` and `capture_bounded` claims only. `true_pit` needs
an artifact proving that exact content version was published, which no rule over
stored rows can produce — expect true-PIT coverage to stay at zero until a source
adapter for it exists.
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import psycopg

from uw_scan.config import Settings
from uw_scan.fundamentals.observation_time import audit_violations
from uw_scan.storage.fundamental_observation_availability import (
    FundamentalObsAvailabilityRepository,
)
from uw_scan.worker.jobs.fundamental_observation_availability import (
    fundamental_observation_availability,
)


def _git_commit() -> str:
    """The code that produced the artifact. An audit that cannot be tied to a
    commit cannot be reproduced, and an unreproducible number did not happen."""
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
    except Exception as exc:
        return f"unknown ({exc!r})"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tickers", help="comma-separated scope; default is every row")
    ap.add_argument("--batch-size", type=int, default=5000)
    ap.add_argument(
        "--max-batches",
        type=int,
        help="stop after N batches so a slice can be inspected before resuming",
    )
    ap.add_argument(
        "--counts", action="store_true", help="report class coverage, write nothing"
    )
    ap.add_argument(
        "--audit",
        metavar="PATH",
        help="write the coverage artifact as JSON and run its self-checks, "
        "writing nothing to the database. Exits non-zero if a check fails.",
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    settings = Settings.from_env()

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = FundamentalObsAvailabilityRepository(conn, schema=settings.db_schema)

        if args.audit:
            report = repo.coverage_audit()
            report["generated"] = {
                "host": settings.db_host,
                "database": settings.db_name,
                "schema": settings.db_schema,
                "commit": _git_commit(),
                "command": " ".join(sys.argv),
                "completed_at": datetime.now(UTC).isoformat(),
            }
            problems = audit_violations(report)
            report["self_check"] = {"passed": not problems, "problems": problems}
            out = Path(args.audit)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(json.dumps(report, indent=2, default=str) + "\n")
            print(f"wrote {out}")
            for line in problems:
                print(f"  FAIL {line}")
            return 1 if problems else 0

        if args.counts:
            counts = repo.claim_counts()
            unclaimed = repo.unclaimed_observation_count()
            for cls, n in sorted(counts.items()):
                print(f"  {cls.value:<16} {n:,}")
            if not counts:
                print("  (no claims recorded)")
            print(f"  {'unclaimed rows':<16} {unclaimed:,}")
            return 0

        totals = fundamental_observation_availability(
            conn=conn,
            schema=settings.db_schema,
            tickers=args.tickers.split(",") if args.tickers else None,
            batch_size=args.batch_size,
            max_batches=args.max_batches,
        )
        remaining = repo.unclaimed_observation_count()

    print(totals)
    print(f"unclaimed observations remaining: {remaining:,}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
