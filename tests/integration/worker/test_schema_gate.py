"""Workers wait for the schema their code needs (I-05).

Watchtower ignores ``depends_on``, so a worker can boot new code before the api has
migrated. ``scheduler.main()`` calls ``wait_for_schema`` before it builds any job;
these tests drive the real gate against the real test DB.
"""

from __future__ import annotations

import logging
import threading

import psycopg
import pytest

from uw_scan.storage.migrate_runner import (
    apply_migrations,
    discover_migrations,
    record_schema_version,
)
from uw_scan.worker.schema_gate import (
    applied_migration,
    expected_migration,
    wait_for_schema,
)

pytestmark = pytest.mark.integration


def test_a_full_apply_records_the_newest_migration(seeded_db_empty_cards):
    assert applied_migration(seeded_db_empty_cards.conn) == expected_migration()


def test_a_db_without_the_marker_table_reads_as_not_migrated(seeded_db_empty_cards):
    """Before 158 exists (fresh or old DB) the gate must wait, not crash. DDL is
    transactional, so the drop is rolled back."""
    conn = seeded_db_empty_cards.conn
    conn.execute("DROP TABLE uw_scan.schema_version")
    try:
        assert applied_migration(conn) is None
    finally:
        conn.rollback()
    assert applied_migration(conn) == expected_migration()


def test_worker_one_migration_behind_waits_then_proceeds_after_migrate(
    seeded_db_empty_cards, _migrated_settings, caplog
):
    conn = seeded_db_empty_cards.conn
    previous = discover_migrations()[-2].name
    conn.execute("UPDATE uw_scan.schema_version SET last_migration = %s", (previous,))
    conn.commit()
    dsn = _migrated_settings.db_dsn()

    polled = threading.Event()
    result: dict[str, str] = {}

    def _sleep(_seconds: float) -> None:
        polled.set()
        threading.Event().wait(0.05)

    caplog.set_level(logging.INFO, logger="uw_scan.worker.schema_gate")
    worker = threading.Thread(
        target=lambda: result.update(have=wait_for_schema(dsn, sleep=_sleep)),
        daemon=True,
    )
    worker.start()
    assert polled.wait(5), "the gate never polled"
    assert worker.is_alive(), "the gate let new code run on an old schema"
    assert any("waiting for migrations" in r.message for r in caplog.records)
    assert all(r.levelno == logging.INFO for r in caplog.records)

    with psycopg.connect(dsn, autocommit=True) as migrate_conn:
        apply_migrations(migrate_conn, log=lambda _msg: None)
    worker.join(10)

    assert not worker.is_alive()
    assert result["have"] == expected_migration()
    with conn.cursor() as cur:
        cur.execute("SELECT count(*) FROM uw_scan.job_failures")
        assert cur.fetchone()[0] == 0  # waiting is not a failure


def test_the_marker_never_moves_backwards(seeded_db_empty_cards, _migrated_settings):
    """A rollback image re-running its shorter chain keeps the newer objects, so
    the marker must keep the newer name."""
    seeded_db_empty_cards.conn.rollback()
    with psycopg.connect(_migrated_settings.db_dsn(), autocommit=True) as conn:
        record_schema_version(conn, "001_older.sql")
        assert applied_migration(conn) == expected_migration()
