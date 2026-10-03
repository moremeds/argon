"""volatility_backfill_tick against a real schema (migration 157 queue)."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone

import psycopg
import pytest

import uw_scan.worker.jobs.volatility_backfill as job_mod
from uw_scan.storage.repository import Repository


class _NoUw:
    def __init__(self, *_a, **_k) -> None:
        pass

    def __enter__(self):
        return self

    def __exit__(self, *_exc):
        return False


@pytest.fixture
def repo(seeded_db_empty_cards, monkeypatch) -> Repository:
    monkeypatch.setattr(job_mod, "UwClient", _NoUw)
    return seeded_db_empty_cards


def _row(repo, ticker):
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT status, started_at, error_message "
            "FROM uw_scan.volatility_backfill_status WHERE ticker = %s",
            (ticker,),
        )
        row = cur.fetchone()
    repo.conn.commit()
    return row


def _tick(repo, settings, *, budget_ok=lambda: True):
    return job_mod.volatility_backfill_tick(
        repo=repo, settings=settings, budget_ok=budget_ok
    )


def _ok_backfill(monkeypatch, calls):
    def fake(*, client, repo, run_id, ticker, nearest_expiries):
        calls.append(ticker)
        return "ready"

    monkeypatch.setattr(job_mod, "run_volatility_backfill", fake)


def test_empty_queue_does_nothing_and_skips_the_budget_read(repo, _migrated_settings):
    def never():
        raise AssertionError("budget read on an empty queue")

    assert _tick(repo, _migrated_settings, budget_ok=never) is None


def test_exhausted_budget_leaves_the_row_queued(
    repo, _migrated_settings, monkeypatch, caplog
):
    calls: list[str] = []
    _ok_backfill(monkeypatch, calls)
    repo.enqueue_volatility_backfill("AAA")
    repo.enqueue_volatility_backfill("BBB")

    with caplog.at_level("INFO", logger=job_mod.__name__):
        assert _tick(repo, _migrated_settings, budget_ok=lambda: False) is None

    assert calls == []
    assert _row(repo, "AAA")[0] == "queued" and _row(repo, "BBB")[0] == "queued"
    assert sum("budget exhausted" in r.message for r in caplog.records) == 1


def test_tick_claims_one_row_and_marks_it_ready(repo, _migrated_settings, monkeypatch):
    calls: list[str] = []
    _ok_backfill(monkeypatch, calls)
    repo.enqueue_volatility_backfill("AAA")
    repo.enqueue_volatility_backfill("BBB")

    assert _tick(repo, _migrated_settings) == "AAA"
    assert calls == ["AAA"]
    assert _row(repo, "AAA")[0] == "ready"
    assert _row(repo, "BBB")[0] == "queued"  # one per tick


def test_stale_running_row_is_requeued_and_rerun(repo, _migrated_settings, monkeypatch):
    calls: list[str] = []
    _ok_backfill(monkeypatch, calls)
    now = datetime.now(timezone.utc)
    repo.upsert_volatility_backfill_status(
        ticker="DEAD", status="running", started_at=now - timedelta(hours=2)
    )
    repo.upsert_volatility_backfill_status(
        ticker="LIVE", status="running", started_at=now - timedelta(minutes=5)
    )
    repo.conn.commit()

    assert _tick(repo, _migrated_settings) == "DEAD"
    assert calls == ["DEAD"]
    assert _row(repo, "DEAD")[0] == "ready"
    assert _row(repo, "LIVE")[0] == "running"  # inside the cut-off: untouched


def test_failed_backfill_persists_failed_then_raises(
    repo, _migrated_settings, monkeypatch
):
    def boom(**_k):
        raise RuntimeError("uw 500")

    monkeypatch.setattr(job_mod, "run_volatility_backfill", boom)
    repo.enqueue_volatility_backfill("AAA")

    with pytest.raises(RuntimeError, match="uw 500"):
        _tick(repo, _migrated_settings)

    status, _started, error = _row(repo, "AAA")
    assert status == "failed" and "uw 500" in error
    # The advisory lock was released: a fresh session can take it.
    with psycopg.connect(_migrated_settings.db_dsn()) as other:
        assert job_mod._try_acquire_backfill_lock(other, "AAA")


def test_second_claim_while_first_holds_the_lock_does_not_run(
    repo, _migrated_settings, monkeypatch
):
    """A stale requeue can hand a still-running ticker to a second claim; the
    session advisory lock keeps the second run out."""
    calls: list[str] = []
    _ok_backfill(monkeypatch, calls)
    repo.enqueue_volatility_backfill("AAA")

    with psycopg.connect(_migrated_settings.db_dsn()) as first:
        assert job_mod._try_acquire_backfill_lock(first, "AAA")
        assert _tick(repo, _migrated_settings) == "AAA"

    assert calls == []
    assert _row(repo, "AAA")[0] == "running"


def test_migration_157_reruns_cleanly(repo):
    """Every API boot re-applies every migration: 157 must be a no-op twice."""
    from pathlib import Path

    import uw_scan.storage as storage_pkg

    sql = (
        Path(storage_pkg.__file__).parent
        / "migrations"
        / "157_volatility_backfill_queue.sql"
    ).read_text()
    for _ in range(2):
        with repo.conn.cursor() as cur:
            cur.execute(sql)
        repo.conn.commit()
    repo.enqueue_volatility_backfill("AAA")
    assert _row(repo, "AAA")[0] == "queued"
