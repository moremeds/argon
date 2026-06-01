"""Locks in the fix from PR #108: insert_scan_run and finish_scan_run must
commit, so rows persist after the connection closes.

The pre-patch bug was 3,234 SPY scan_runs rows stuck `status='running'` over
16+ days because `finish_scan_run`'s trailing UPDATE was rolled back at
`conn.close()`. These tests guard against that regression — if either commit
is removed, both tests fail.
"""

from __future__ import annotations

import psycopg

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository


def _fresh_repo(settings: Settings) -> Repository:
    conn = psycopg.connect(settings.db_dsn())
    return Repository(conn, schema=settings.db_schema)


def test_insert_scan_run_persists_after_conn_close(seeded_db_empty_cards):
    """insert_scan_run must commit so the row survives a non-autocommit close."""
    seed_repo = seeded_db_empty_cards
    settings = Settings.from_env().model_copy(
        update={"db_name": seed_repo.conn.info.dbname}
    )

    repo = _fresh_repo(settings)
    try:
        run_id = repo.insert_scan_run(ticker="TEST", notes="commit_test_insert")
    finally:
        repo.conn.close()

    verify = _fresh_repo(settings)
    try:
        with verify.conn.cursor() as cur:
            cur.execute(
                "SELECT status, notes FROM uw_scan.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
    finally:
        verify.conn.close()

    assert row is not None, "row should persist after the writer's conn closed"
    assert row[0] == "running", "freshly-inserted row carries the default status"
    assert row[1] == "commit_test_insert"


def test_finish_scan_run_seals_after_conn_close(seeded_db_empty_cards):
    """finish_scan_run must commit so finished_at + status='ok' survive close."""
    seed_repo = seeded_db_empty_cards
    settings = Settings.from_env().model_copy(
        update={"db_name": seed_repo.conn.info.dbname}
    )

    repo = _fresh_repo(settings)
    try:
        run_id = repo.insert_scan_run(ticker="TEST", notes="commit_test_finish")
        repo.finish_scan_run(run_id, status="ok")
    finally:
        repo.conn.close()

    verify = _fresh_repo(settings)
    try:
        with verify.conn.cursor() as cur:
            cur.execute(
                "SELECT status, finished_at FROM uw_scan.scan_runs WHERE run_id=%s",
                (run_id,),
            )
            row = cur.fetchone()
    finally:
        verify.conn.close()

    assert row is not None
    assert row[0] == "ok", "status must be sealed after conn close (pre-PR-108 bug)"
    assert row[1] is not None, (
        "finished_at must be set after conn close (pre-PR-108 bug)"
    )
