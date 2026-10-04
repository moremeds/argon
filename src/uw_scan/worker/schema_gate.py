"""Hold a worker until the DB schema is at least as new as its code (I-05).

Watchtower ignores ``depends_on``, so on a deploy the worker containers can start
the new image before the api container has run its migrations. New code against
an old schema fails in the first job that touches a new column or table, and
records that as a job failure. Instead the worker waits here, before its scheduler
is built: it reads the marker ``migrate_runner`` writes after a full apply
(``uw_scan.schema_version``, migration 158) and compares it with the newest
migration file shipped in its own image.

Waiting is not a failure: it logs at INFO and retries, and nothing reaches
``job_failures`` because no job has been scheduled yet.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from pathlib import Path

import psycopg

from uw_scan.storage.migrate_runner import MIGRATIONS_DIR, discover_migrations

logger = logging.getLogger(__name__)

DEFAULT_POLL_SECONDS = 15.0
#: The wait is logged at most this often, so a long deploy window stays readable.
LOG_EVERY_SECONDS = 60.0


def expected_migration(migrations_dir: Path = MIGRATIONS_DIR) -> str:
    """The newest migration file this code ships with."""
    name = discover_migrations(migrations_dir)[-1].name
    # ponytail: plain string order (== discover_migrations' sort == COLLATE "C") is
    # migration order only while every prefix has 3 digits; past 999, '1000_' sorts
    # before '999_'. Fail loudly at that ceiling instead of gating on the wrong file.
    if not (name[:3].isdigit() and name[3] == "_"):
        raise RuntimeError(f"migration {name!r} lacks a 3-digit prefix; fix the gate")
    return name


def schema_is_ready(applied: str | None, expected: str) -> bool:
    """Ready when the DB is migrated at least as far as this image needs.

    ``applied`` ahead of ``expected`` is ready too: that is an older image after a
    rollback, running against newer (additive) objects. No marker means not ready:
    migration 158 has not been applied yet.
    """
    return applied is not None and applied >= expected


def applied_migration(conn: psycopg.Connection) -> str | None:
    """The marker, or None while migration 158 itself has not been applied."""
    if (
        conn.execute("SELECT to_regclass('uw_scan.schema_version')").fetchone()[0]
        is None
    ):
        return None
    row = conn.execute("SELECT last_migration FROM uw_scan.schema_version").fetchone()
    return row[0] if row else None


def wait_for_schema(
    dsn: str,
    *,
    expected: str | None = None,
    poll_seconds: float = DEFAULT_POLL_SECONDS,
    sleep: Callable[[float], None] = time.sleep,
    clock: Callable[[], float] = time.monotonic,
) -> str:
    """Block until the applied marker sorts at or after ``expected``; return it."""
    want = expected or expected_migration()
    last_log: float | None = None
    while True:
        try:
            with psycopg.connect(dsn) as conn:
                have = applied_migration(conn)
        except psycopg.OperationalError as exc:
            have, why = None, f"database unreachable: {exc!r}"
        else:
            if schema_is_ready(have, want):
                logger.info("schema gate: schema at %s (code needs %s)", have, want)
                return have
            why = f"database at {have or '<no marker>'}"
        now = clock()
        if last_log is None or now - last_log >= LOG_EVERY_SECONDS:
            logger.info(
                "schema gate: waiting for migrations; %s, code needs %s",
                why,
                want,
            )
            last_log = now
        sleep(poll_seconds)
