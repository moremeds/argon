from types import SimpleNamespace

import psycopg
import pytest

from uw_scan.storage.ops_health import JobFailuresRepository
from uw_scan.storage.repository import Repository
from uw_scan.worker import scheduler


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_error_event_records_streak(repo, monkeypatch):
    # _handle_job_event opens `with _ops_conn() as conn:`. On psycopg 3.3.4
    # (verified empirically) Connection.__exit__ closes any non-pooled
    # connection after commit — it does NOT leave it open. So handing the
    # handler `repo.conn` directly would close the fixture's connection out
    # from under the assertion below. Route it to a second, real connection
    # against the same test DB instead: the handler's copy gets closed as
    # designed (matches production's fresh-conn-per-event behaviour) while
    # `repo.conn` stays open for readback.
    dsn = repo.conn.info.dsn
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )
    scheduler._handle_job_event(
        SimpleNamespace(job_id="full_scan", exception=RuntimeError("boom"))
    )
    assert JobFailuresRepository(repo.conn).list_streaks()[0].job_name == "full_scan"


def test_alert_fires_only_on_third_consecutive_failure(repo, monkeypatch):
    # send_alert is imported inside _handle_job_event at call time
    # (`from uw_scan.alerts import send_alert`), so the spy must patch the
    # source module, not the scheduler module.
    dsn = repo.conn.info.dsn
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )
    calls = []
    monkeypatch.setattr(
        "uw_scan.alerts.send_alert", lambda *a, **k: calls.append((a, k))
    )

    for _ in range(3):
        scheduler._handle_job_event(
            SimpleNamespace(job_id="full_scan", exception=RuntimeError("boom"))
        )

    assert len(calls) == 1
    args, kwargs = calls[0]
    joined = " ".join(str(x) for x in (*args, *kwargs.values()))
    assert "full_scan" in joined
    assert "3" in joined
