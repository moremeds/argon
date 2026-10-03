from types import SimpleNamespace

import psycopg
import pytest

from uw_scan.storage.ops_health import JobFailuresRepository
from uw_scan.storage.repository import Repository
from uw_scan.worker import scheduler


@pytest.fixture
def repo(seeded_db_empty_cards) -> Repository:
    return seeded_db_empty_cards


def test_error_event_records_streak(repo, _migrated_settings, monkeypatch):
    # _handle_job_event opens `with _ops_conn() as conn:`. On psycopg 3.3.4
    # Connection.__exit__ closes any non-pooled connection after commit, so
    # handing the handler `repo.conn` directly would close the fixture's
    # connection out from under the readback below. Route it to a second, real
    # connection to the same test DB instead: the handler's copy gets closed as
    # designed (matches production's fresh-conn-per-event behaviour) while
    # `repo.conn` stays open for readback.
    #
    # Build the DSN from the settings (it carries auth). NOT
    # `repo.conn.info.dsn` — psycopg REDACTS the password there, so a reconnect
    # fails under CI's password auth (`fe_sendauth: no password supplied`).
    dsn = _migrated_settings.db_dsn()
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )
    scheduler._handle_job_event(
        SimpleNamespace(job_id="full_scan", exception=RuntimeError("boom"))
    )
    assert JobFailuresRepository(repo.conn).list_streaks()[0].job_name == "full_scan"


def test_alert_fires_only_on_third_consecutive_failure(
    repo, _migrated_settings, monkeypatch
):
    # send_alert is imported inside _handle_job_event at call time
    # (`from uw_scan.alerts import send_alert`), so the spy must patch the
    # source module, not the scheduler module.
    # DSN from settings (carries auth); `repo.conn.info.dsn` redacts the
    # password and fails under CI's password auth.
    dsn = _migrated_settings.db_dsn()
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


def test_market_tide_sentiment_failure_streak_then_success_clears(
    repo, _migrated_settings, monkeypatch
):
    """The real `market_tide_sentiment_eod` closure, run against the test DB,
    must feed the listener: two failed runs -> streak 2; one good run -> cleared.

    Before the fix the closure swallowed the error, so APScheduler saw a
    success and the streak never moved.
    """
    from contextlib import contextmanager

    import uw_scan.worker.jobs.market_tide_sentiment as sentiment_mod

    job_id = "market_tide_sentiment_eod"
    dsn = _migrated_settings.db_dsn()
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )

    @contextmanager
    def test_repo(_settings):
        yield repo

    captured: dict[str, object] = {}

    class _StopStart(Exception):
        pass

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            if kwargs.get("id") == job_id and args:
                captured["func"] = args[0]

        def start(self) -> None:
            raise _StopStart

    class _FakeSignal:
        SIGTERM = 15
        SIGINT = 2

        def signal(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    monkeypatch.setattr(scheduler, "_repo", test_repo)
    monkeypatch.setenv("UW_SCAN_WORKER_ROLE", "uw")
    monkeypatch.setenv("UW_SCAN_WORKER_INDEX", "0")
    monkeypatch.setenv("UW_SCAN_WORKER_COUNT", "1")
    monkeypatch.setenv("MARKET_TIDE_CAPTURE_ENABLED", "true")
    with pytest.raises(_StopStart):
        scheduler.main()
    job = captured["func"]

    def run_and_report() -> None:
        # What APScheduler does: run the job, emit EVENT_JOB_ERROR with the
        # exception or EVENT_JOB_EXECUTED without one.
        try:
            job()
        except Exception as exc:
            scheduler._handle_job_event(SimpleNamespace(job_id=job_id, exception=exc))
        else:
            scheduler._handle_job_event(SimpleNamespace(job_id=job_id, exception=None))

    real_refresh = sentiment_mod.refresh_eod_sentiment

    def boom(*_a, **_k):
        raise RuntimeError("sentiment boom")

    monkeypatch.setattr(sentiment_mod, "refresh_eod_sentiment", boom)
    run_and_report()
    run_and_report()

    streaks = {s.job_name: s for s in JobFailuresRepository(repo.conn).list_streaks()}
    assert streaks[job_id].consecutive == 2
    assert "sentiment boom" in streaks[job_id].last_error

    # The real job on an empty tide table persists nothing and returns 0: a
    # normal outcome, so the listener records success and clears the streak.
    monkeypatch.setattr(sentiment_mod, "refresh_eod_sentiment", real_refresh)
    run_and_report()

    assert job_id not in {
        s.job_name for s in JobFailuresRepository(repo.conn).list_streaks()
    }


def test_top_net_impact_failure_streak_matches_scan_runs_then_success_clears(
    repo, _migrated_settings, monkeypatch
):
    """The real `regime_top_net_impact_scan` closure and scanner, run against
    the test DB: two failed UW fetches -> two 'error' scan_runs and streak 2;
    one good fetch -> an 'ok' scan_run and the streak cleared.

    Before the fix the closure swallowed the error, so the scan_run said
    'error' while the listener recorded a success.
    """
    from contextlib import contextmanager
    from datetime import datetime as real_datetime

    import uw_scan.sources.uw as uw_source

    job_id = "regime_top_net_impact_scan"
    dsn = _migrated_settings.db_dsn()
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )

    @contextmanager
    def test_repo(_settings):
        yield repo

    @contextmanager
    def no_recorder(_settings):
        yield None

    class _NoUw:
        def __enter__(self):
            return self

        def __exit__(self, *exc_info):
            return False

    class _Thursday(real_datetime):
        @classmethod
        def now(cls, tz=None):
            return real_datetime(2026, 10, 1, 11, 0, tzinfo=tz)

    captured: dict[str, object] = {}

    class _StopStart(Exception):
        pass

    class _FakeSched:
        def __init__(self, *_a, **_k) -> None:
            pass

        def add_listener(self, *_a, **_k) -> None:
            pass

        def add_job(self, *args, **kwargs) -> None:
            if kwargs.get("id") == job_id and args:
                captured["func"] = args[0]

        def start(self) -> None:
            raise _StopStart

    class _FakeSignal:
        SIGTERM = 15
        SIGINT = 2

        def signal(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    monkeypatch.setattr(scheduler, "datetime", _Thursday)
    monkeypatch.setattr(scheduler, "_repo", test_repo)
    monkeypatch.setattr(scheduler, "_external_api_recorder", no_recorder)
    monkeypatch.setattr(scheduler, "_uw_client", lambda *a, **k: _NoUw())
    monkeypatch.setenv("UW_SCAN_WORKER_ROLE", "uw")
    monkeypatch.setenv("UW_SCAN_WORKER_INDEX", "0")
    monkeypatch.setenv("UW_SCAN_WORKER_COUNT", "1")
    monkeypatch.setenv("TOP_NET_IMPACT_CAPTURE_ENABLED", "true")
    with pytest.raises(_StopStart):
        scheduler.main()
    job = captured["func"]

    def run_and_report() -> None:
        try:
            job()
        except Exception as exc:
            scheduler._handle_job_event(SimpleNamespace(job_id=job_id, exception=exc))
        else:
            scheduler._handle_job_event(SimpleNamespace(job_id=job_id, exception=None))

    def statuses() -> list[str]:
        with repo.conn.cursor() as cur:
            cur.execute(
                "SELECT status FROM uw_scan.scan_runs WHERE notes = %s ORDER BY run_id",
                (job_id,),
            )
            return [r[0] for r in cur.fetchall()]

    def boom(*_a, **_k):
        raise RuntimeError("tni boom")

    monkeypatch.setattr(uw_source, "fetch_top_net_impact", boom)
    run_and_report()
    run_and_report()

    streaks = {s.job_name: s for s in JobFailuresRepository(repo.conn).list_streaks()}
    assert statuses() == ["error", "error"]
    assert streaks[job_id].consecutive == 2
    assert "tni boom" in streaks[job_id].last_error

    # Zero rows published is a normal outcome: an 'ok' run, streak cleared.
    monkeypatch.setattr(uw_source, "fetch_top_net_impact", lambda *a, **k: [])
    run_and_report()

    assert statuses() == ["error", "error", "ok"]
    assert job_id not in {
        s.job_name for s in JobFailuresRepository(repo.conn).list_streaks()
    }
