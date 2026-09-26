"""Persist per-table record-health counts so /api/health never sweeps tables.

The sweep (COUNT / COUNT DISTINCT ticker / MAX(ts) over every record-health rule
table, option_contract_snapshots included) used to run on the API request path,
once per HealthPanel poll. It now runs here, on uw-0 every 15 minutes, and the
API reads ``uw_scan.record_health_snapshot`` (migration 151) and applies the
coverage thresholds at request time.
"""

from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from datetime import UTC, datetime, timedelta

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

logger = logging.getLogger(__name__)


def refresh_record_health_snapshot(
    repo: Repository,
    *,
    now_utc: datetime,
    window_hours: float,
    daily_window_hours: float,
) -> int:
    """Compute raw counts for every rule table and replace the snapshot."""
    rows = repo.compute_record_health_raw(
        since=now_utc - timedelta(hours=window_hours),
        # Daily tables (nightly vol rollup, daily snapshots) refresh once per
        # day, so they need a wider window to count as fresh.
        daily_since=now_utc - timedelta(hours=daily_window_hours),
    )
    return repo.upsert_record_health_snapshot(rows)


@contextmanager
def _repo(settings: Settings) -> Iterator[Repository]:
    # `with psycopg.connect(...)` commits on clean exit; closing a bare
    # connection would discard (see worker/scheduler._repo).
    with psycopg.connect(settings.db_dsn()) as conn:
        yield Repository(conn, schema=settings.db_schema)


def record_health_snapshot_job(settings: Settings) -> int:
    started = datetime.now(UTC)
    with _repo(settings) as repo:
        written = refresh_record_health_snapshot(
            repo,
            now_utc=started,
            window_hours=settings.record_health_window_hours,
            daily_window_hours=settings.record_health_daily_window_hours,
        )
    logger.info(
        "record_health_snapshot: %d tables in %.1fs",
        written,
        (datetime.now(UTC) - started).total_seconds(),
    )
    return written
