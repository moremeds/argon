"""Run the tier-1 fundamental statement ingest (migration 114).

    uv run python scripts/backfill/fundamental_ingest_backfill.py [--tier ranked]
                                                                 [--tickers NVDA,MSFT]
                                                                 [--coverage]

Entry point for `worker/jobs/fundamental_ingest.py` until the scheduler wires it.
The job itself holds all the logic — this script only builds the client and the
connection, so a scheduled run and a manual run cannot drift apart.

Cost: 4 UW calls per ticker (3 statements + 1 filing-date breakdown). The full
`ranked` tier is ~1,030 calls against a 120k/day budget. Statements are quarterly,
so this is not a daily job.
"""

from __future__ import annotations

import argparse
import logging
import sys

import psycopg

from uw_scan.api.client import UwClient
from uw_scan.config import Settings
from uw_scan.storage.fundamental_obs import FundamentalObsRepository
from uw_scan.storage.provider_usage import ExternalApiRequestRecorder
from uw_scan.worker.jobs.fundamental_ingest import fundamental_ingest


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tier", default="ranked")
    ap.add_argument("--tickers", help="comma-separated override, bypasses the tier")
    ap.add_argument(
        "--coverage", action="store_true", help="report what landed, ingest nothing"
    )
    args = ap.parse_args()

    logging.basicConfig(
        level=logging.INFO, format="%(asctime)s %(levelname)-7s %(message)s"
    )
    settings = Settings.from_env()

    with psycopg.connect(settings.db_dsn()) as conn:
        repo = FundamentalObsRepository(conn, schema=settings.db_schema)

        if args.coverage:
            rows = repo.coverage(args.tier)
            landed = [r for r in rows if r["rows"]]
            print(f"tier {args.tier}: {len(landed)}/{len(rows)} tickers with rows")
            if landed:
                periods = sorted(r["periods"] for r in landed)
                filed = sum(r["with_filing_date"] for r in landed)
                total = sum(r["rows"] for r in landed)
                print(f"  rows                {total:,}")
                print(
                    f"  periods per ticker  min {periods[0]} / median "
                    f"{periods[len(periods) // 2]} / max {periods[-1]}"
                )
                print(f"  with real filing date {filed:,} ({100 * filed / total:.1f}%)")
            empty = [r["ticker"] for r in rows if not r["rows"]]
            if empty:
                print(
                    f"  no rows ({len(empty)}): {', '.join(empty[:20])}"
                    + (" ..." if len(empty) > 20 else "")
                )
            return 0

        recorder = ExternalApiRequestRecorder(
            settings.db_dsn(), schema=settings.db_schema
        )
        try:
            client = UwClient(
                api_key=settings.api_key.get_secret_value(),
                base_url=settings.base_url,
                timeout=settings.request_timeout_seconds,
                telemetry_recorder=recorder,
                job_name="fundamental_ingest_backfill",
            )
            totals = fundamental_ingest(
                conn=conn,
                client=client,
                tier=args.tier,
                schema=settings.db_schema,
                tickers=args.tickers.split(",") if args.tickers else None,
            )
        finally:
            recorder.close()

    print(totals)
    return 0 if totals["failed"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
