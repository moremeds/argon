"""Run one live FRED-backed US rates ingest and snapshot compute."""

from __future__ import annotations

import argparse
import sys

from uw_scan.config import Settings
from uw_scan.worker.jobs.rates_jobs import rates_fred_ingest_job


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Fetch live FRED rates observations and persist one rates snapshot."
    )
    parser.add_argument(
        "--lookback-days",
        type=int,
        default=90,
        help="Number of calendar days of FRED observations to fetch.",
    )
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    if args.lookback_days < 1:
        print("--lookback-days must be >= 1", file=sys.stderr)
        return 2

    settings = Settings.from_env()
    if settings.fred_api_key is None:
        print("FRED_API_KEY is required for rates backfill.", file=sys.stderr)
        return 2

    result = rates_fred_ingest_job(
        dsn=settings.db_dsn(),
        fred_api_key=settings.fred_api_key.get_secret_value(),
        schema=settings.db_schema,
        lookback_days=args.lookback_days,
        policy_path_url=settings.rates_policy_path_url,
    )

    print(f"inserted_observations={result.inserted_observations}")
    print(f"failed_series_count={len(result.failed_series)}")
    if result.failed_series:
        print(f"failed_series={','.join(result.failed_series)}")
    print(f"snapshot_date={result.snapshot_date.isoformat()}")
    print(f"computed_at={result.computed_at.isoformat()}")
    return 1 if result.failed_series else 0


if __name__ == "__main__":
    raise SystemExit(main())
