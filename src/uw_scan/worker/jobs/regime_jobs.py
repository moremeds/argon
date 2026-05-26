"""Phase 0.5 — FRED ingestion for regime classification.

NFCI / ANFCI / USREC are the three series the Level-1 regime label contract
depends on for the credit-stress (NFCI/ANFCI) and recession (USREC) gates.
These series were not part of the original gold FRED registry; this job
keeps them isolated from the gold pipeline so an outage in one domain
does not break the other.

Schedule: weekly (NFCI publishes Wednesdays for the prior Friday).
Backfill: run `uv run python -m uw_scan.worker.jobs.regime_jobs --backfill
--start 2007-01-01` for the full historical window.
"""

from __future__ import annotations

import argparse
import logging
from datetime import UTC, date, datetime, timedelta

import psycopg

from uw_scan.sources.fred import FredProvider
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


REGIME_FRED_SERIES_DAILY: tuple[str, ...] = ("NFCI", "ANFCI", "USREC")


def regime_fred_ingest_job(
    *,
    dsn: str,
    series_ids: tuple[str, ...] | None = None,
    lookback_days: int = 45,
    schema: str = "uw_scan",
) -> dict[str, int]:
    """Refresh NFCI / ANFCI / USREC into macro_series_daily.

    Mirrors gold_fred_ingest_job's CSV-based pattern (no API key required).
    Returns {series_id: inserted_rows} for telemetry. Idempotent via
    ON CONFLICT (series_id, obs_date, as_of) DO NOTHING in the insert.

    For initial backfill, pass lookback_days large enough to cover history
    (e.g., 7000 for 2007→present).
    """
    ids = series_ids or REGIME_FRED_SERIES_DAILY
    now = datetime.now(UTC)
    start = date.today() - timedelta(days=lookback_days)
    inserted: dict[str, int] = {}
    with (
        psycopg.connect(dsn) as conn,
        FredProvider(job_name="regime_fred_ingest") as fred,
    ):
        repo = Repository(conn, schema=schema)
        for sid in ids:
            try:
                obs = fred.fetch_series(sid, start=start)
                rows = [
                    {
                        "series_id": o.series_id,
                        "obs_date": o.obs_date,
                        "value": o.value,
                        "release_date": None,
                        "source_url": "https://fred.stlouisfed.org",
                    }
                    for o in obs
                ]
                n = repo.insert_macro_series_daily_rows(rows, as_of=now, source="FRED")
                inserted[sid] = n
                logger.info("regime_fred_ingest: series=%s inserted=%d", sid, n)
            except Exception as exc:
                inserted[sid] = 0
                logger.exception("regime_fred_ingest: series=%s failed: %r", sid, exc)
        conn.commit()
    return inserted


def _main() -> int:
    parser = argparse.ArgumentParser(description="Backfill regime FRED series.")
    parser.add_argument(
        "--start",
        type=str,
        default="2007-01-01",
        help="Earliest obs_date to fetch (default 2007-01-01)",
    )
    parser.add_argument(
        "--series",
        type=str,
        nargs="+",
        default=None,
        help="Override default series list",
    )
    args = parser.parse_args()
    from uw_scan.config import Settings  # local to keep CLI import light

    logging.basicConfig(
        level=logging.INFO,
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
    dsn = Settings.from_env().db_dsn()
    start = date.fromisoformat(args.start)
    lookback_days = (date.today() - start).days
    series = tuple(args.series) if args.series else None
    inserted = regime_fred_ingest_job(
        dsn=dsn, series_ids=series, lookback_days=lookback_days
    )
    for sid, n in inserted.items():
        print(f"  {sid}: {n} rows")
    total = sum(inserted.values())
    print(f"TOTAL: {total} rows inserted")
    return 0 if any(inserted.values()) else 1


if __name__ == "__main__":
    raise SystemExit(_main())
