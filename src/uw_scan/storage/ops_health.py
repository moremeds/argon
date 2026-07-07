"""Ops-hardening health state: job-failure streaks.

New domain module (see CLAUDE.md 'Never extend repository.py') — a standalone
repository used by direct import (health route, scheduler listener), NOT added
to the assembled `Repository`.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

from psycopg import Connection

_SCHEMA = "uw_scan"


def _ops_conn() -> Connection:
    """Short-lived conn for ops telemetry writes from the (env-frozen) worker.

    Matches the house factory: workers/migrate_runner/provider_usage all do
    `psycopg.connect(settings.db_dsn(), autocommit=True)`. There is NO
    `storage.connection.connect` helper — verified 2026-07-07.
    """
    import psycopg

    from uw_scan.config import Settings

    return psycopg.connect(Settings().db_dsn(), autocommit=True)


@dataclass(frozen=True)
class JobFailureRow:
    job_name: str
    consecutive: int
    last_error: str
    last_failed_at: datetime


class JobFailuresRepository:
    def __init__(self, conn: Connection) -> None:
        self._conn = conn

    def record_failure(self, job_name: str, error: str) -> None:
        # Streak is keyed by job_name only, so it is an aggregate across sharded
        # worker processes (e.g. full_scan on uw-0 and uw-1 share one row): a
        # success on any shard resets it. Good enough for systemic failures (all
        # shards fail → streak climbs); a shard-specific failure that another
        # shard's success keeps resetting won't alert — accepted for v1.
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.job_failures
                    (job_name, consecutive, last_error, last_failed_at, updated_at)
                VALUES (%s, 1, %s, now(), now())
                ON CONFLICT (job_name) DO UPDATE SET
                    consecutive = {_SCHEMA}.job_failures.consecutive + 1,
                    last_error = EXCLUDED.last_error,
                    last_failed_at = now(),
                    updated_at = now()
                """,
                (job_name, error[:2000]),
            )

    def record_success(self, job_name: str) -> None:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                INSERT INTO {_SCHEMA}.job_failures
                    (job_name, consecutive, last_success_at, updated_at)
                VALUES (%s, 0, now(), now())
                ON CONFLICT (job_name) DO UPDATE SET
                    consecutive = 0,
                    last_success_at = now(),
                    updated_at = now()
                """,
                (job_name,),
            )

    def list_streaks(self, min_streak: int = 1) -> list[JobFailureRow]:
        with self._conn.cursor() as cur:
            cur.execute(
                f"""
                SELECT job_name, consecutive, last_error, last_failed_at
                FROM {_SCHEMA}.job_failures
                WHERE consecutive >= %s
                ORDER BY consecutive DESC
                """,
                (min_streak,),
            )
            return [
                JobFailureRow(
                    job_name=r[0],
                    consecutive=r[1],
                    last_error=r[2] or "",
                    last_failed_at=r[3],
                )
                for r in cur.fetchall()
            ]
