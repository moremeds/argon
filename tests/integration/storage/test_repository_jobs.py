"""Tests for the rescan jobs queue repository methods, especially the
late-completer race surfaced by 2026-05-16 review (B1) and the codex
review revision (claim-token approach).

Uses the local `repo` fixture pattern (parents-of-parents-of-this-file is the
repo root; UW_SCAN_TEST_DB_NAME must be set; migrations applied per test).
"""

from __future__ import annotations

import os
import subprocess
from datetime import timedelta
from pathlib import Path

import psycopg
import pytest

from uw_scan.config import Settings
from uw_scan.storage.repository import Repository

REPO_ROOT = Path(__file__).resolve().parents[3]


def _test_settings() -> Settings:
    test_db = os.environ.get("UW_SCAN_TEST_DB_NAME")
    if not test_db:
        pytest.fail(
            "UW_SCAN_TEST_DB_NAME is not set; refusing to write into the working DB.",
            pytrace=False,
        )
    os.environ.setdefault("UW_SCAN_API_KEY", "test-dummy-not-used-by-db-tests")
    return Settings.from_env().model_copy(update={"db_name": test_db})


@pytest.fixture
def repo() -> Repository:
    settings = _test_settings()
    with psycopg.connect(settings.db_dsn(), autocommit=True) as conn:
        with conn.cursor() as cur:
            cur.execute("DROP SCHEMA IF EXISTS uw_scan CASCADE")
            cur.execute("CREATE SCHEMA uw_scan")
    env = {**os.environ, "UW_SCAN_DB_NAME": settings.db_name}
    subprocess.run(
        ["bash", str(REPO_ROOT / "scripts/migrate.sh")],
        check=True,
        cwd=REPO_ROOT,
        env=env,
    )
    with psycopg.connect(settings.db_dsn()) as conn:
        yield Repository(conn, schema=settings.db_schema)


def test_mark_job_done_no_op_when_job_was_reclaimed(repo: Repository):
    """B1 race: worker A claims, requeue_stale flips it back, worker B reclaims
    under a fresh claim_token, then worker A finally finishes and tries to mark
    the job done with its OLD token. The mark must be rejected; B's claim
    survives intact."""
    # Worker A claims.
    job_id = repo.enqueue_rescan_job("TSLA")
    job_a = repo.claim_next_queued_job()
    assert job_a is not None
    token_a = job_a.claim_token
    assert token_a is not None

    # Force the started_at into the past so the stale requeue picks it up.
    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.jobs SET started_at=NOW() - INTERVAL '31 minutes' WHERE id=%s",
            (job_id,),
        )
    repo.conn.commit()
    requeued = repo.requeue_stale_running_jobs(timedelta(minutes=30))
    assert requeued == 1

    # Worker B reclaims under a fresh token.
    job_b = repo.claim_next_queued_job()
    assert job_b is not None
    assert job_b.id == job_a.id  # same row
    assert job_b.claim_token != token_a  # new token

    # Worker A's late mark_job_done with its OLD token must be a no-op.
    stale_run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(stale_run_id, status="ok")
    repo.mark_job_done(job_id, stale_run_id, token_a)

    job_after_a = repo.get_job(job_id)
    assert job_after_a is not None
    assert job_after_a.status == "running", "B's claim was overwritten"
    assert job_after_a.claim_token == job_b.claim_token, "B's token was overwritten"
    assert job_after_a.run_id is None or job_after_a.run_id != stale_run_id, (
        "stale run_id was written"
    )

    # Worker B's mark_job_done with the CURRENT token succeeds.
    new_run_id = repo.insert_scan_run("TSLA")
    repo.finish_scan_run(new_run_id, status="ok")
    repo.mark_job_done(job_id, new_run_id, job_b.claim_token)

    final = repo.get_job(job_id)
    assert final is not None
    assert final.status == "done"
    assert final.run_id == new_run_id


def test_mark_job_failed_no_op_when_token_mismatch(repo: Repository):
    """Mirror of the above for mark_job_failed."""
    job_id = repo.enqueue_rescan_job("TSLA")
    job_a = repo.claim_next_queued_job()
    assert job_a is not None

    with repo.conn.cursor() as cur:
        cur.execute(
            f"UPDATE {repo._schema}.jobs SET started_at=NOW() - INTERVAL '31 minutes' WHERE id=%s",
            (job_id,),
        )
    repo.conn.commit()
    repo.requeue_stale_running_jobs(timedelta(minutes=30))
    job_b = repo.claim_next_queued_job()
    assert job_b is not None

    repo.mark_job_failed(job_id, "boom from A", job_a.claim_token)

    after = repo.get_job(job_id)
    assert after is not None
    assert after.status == "running"
    assert after.error is None or "boom from A" not in (after.error or "")
    assert after.claim_token == job_b.claim_token
