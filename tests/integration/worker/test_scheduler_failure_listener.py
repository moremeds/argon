from types import SimpleNamespace

import psycopg
import pytest

from uw_scan.storage.ops_health import JobFailuresRepository
from uw_scan.storage.repository import Repository
from uw_scan.worker import scheduler
from uw_scan.worker.schedule import regime


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
    # main() waits for the schema marker first; this DB is not the one it reads.
    monkeypatch.setattr(scheduler, "wait_for_schema", lambda *_a, **_k: "skipped")
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    monkeypatch.setattr(scheduler, "_repo", test_repo)
    monkeypatch.setattr(regime, "_repo", test_repo)
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


def _capture_uw0_jobs(monkeypatch, repo, job_ids, env):
    """Run `scheduler.main()` with a fake APScheduler and return the real
    closures for `job_ids`, all bound to the test-DB `repo`."""
    from contextlib import contextmanager
    from datetime import datetime as real_datetime

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
            if kwargs.get("id") in job_ids and args:
                captured[kwargs["id"]] = args[0]

        def start(self) -> None:
            raise _StopStart

    class _FakeSignal:
        SIGTERM = 15
        SIGINT = 2

        def signal(self, *_a, **_k) -> None:
            return None

    monkeypatch.setattr(scheduler, "BlockingScheduler", _FakeSched)
    # main() waits for the schema marker first; this DB is not the one it reads.
    monkeypatch.setattr(scheduler, "wait_for_schema", lambda *_a, **_k: "skipped")
    monkeypatch.setattr(scheduler, "signal", _FakeSignal())
    monkeypatch.setattr(scheduler, "datetime", _Thursday)
    monkeypatch.setattr(regime, "datetime", _Thursday)
    monkeypatch.setattr(scheduler, "_repo", test_repo)
    monkeypatch.setattr(regime, "_repo", test_repo)
    monkeypatch.setattr(scheduler, "_external_api_recorder", no_recorder)
    monkeypatch.setattr(regime, "_external_api_recorder", no_recorder)
    monkeypatch.setattr(scheduler, "_uw_client", lambda *a, **k: _NoUw())
    monkeypatch.setattr(regime, "_uw_client", lambda *a, **k: _NoUw())
    monkeypatch.setattr(scheduler, "_research_budget_ok", lambda *a, **k: True)
    monkeypatch.setattr(regime, "_research_budget_ok", lambda *a, **k: True)
    for k, v in {
        "UW_SCAN_WORKER_ROLE": "uw",
        "UW_SCAN_WORKER_INDEX": "0",
        "UW_SCAN_WORKER_COUNT": "1",
        **env,
    }.items():
        monkeypatch.setenv(k, v)
    with pytest.raises(_StopStart):
        scheduler.main()
    assert set(captured) == set(job_ids)
    return captured


def _run_and_report(job_id, job) -> None:
    # What APScheduler does: run the job, emit EVENT_JOB_ERROR with the
    # exception or EVENT_JOB_EXECUTED without one.
    try:
        job()
    except Exception as exc:
        scheduler._handle_job_event(SimpleNamespace(job_id=job_id, exception=exc))
    else:
        scheduler._handle_job_event(SimpleNamespace(job_id=job_id, exception=None))


def _scan_run_statuses(repo, notes_like: str) -> list[str]:
    with repo.conn.cursor() as cur:
        cur.execute(
            "SELECT status FROM uw_scan.scan_runs WHERE notes LIKE %s ORDER BY run_id",
            (notes_like,),
        )
        return [r[0] for r in cur.fetchall()]


def _streaks(repo) -> dict:
    return {s.job_name: s for s in JobFailuresRepository(repo.conn).list_streaks()}


def test_gex_streak_only_when_every_ticker_fails(repo, _migrated_settings, monkeypatch):
    """Unit = one ticker. Every ticker failing (real scanner, failed UW fetch)
    -> one failed run whose scan_runs are all 'error'; a run where one ticker
    fails and the others succeed is a success and clears the streak."""
    import uw_scan.scanners.gex as gex_scanner

    dsn = _migrated_settings.db_dsn()
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )
    job_id = "regime_gex_scan"
    job = _capture_uw0_jobs(
        monkeypatch, repo, {job_id}, {"GEX_SCAN_TICKERS": "SPY,QQQ"}
    )[job_id]

    real_run = gex_scanner.run

    def boom(*_a, **_k):
        raise RuntimeError("iv-rank 500")

    monkeypatch.setattr(gex_scanner, "fetch_iv_rank_rows", boom)
    _run_and_report(job_id, job)

    assert _scan_run_statuses(repo, "gex_scan_%") == ["error", "error"]
    assert _streaks(repo)[job_id].consecutive == 1
    assert "all 2 tickers failed" in _streaks(repo)[job_id].last_error

    # QQQ still fails in the real scanner; SPY succeeds -> the run succeeds.
    monkeypatch.setattr(
        gex_scanner,
        "run",
        lambda uw, r, ticker: 1 if ticker == "SPY" else real_run(uw, r, ticker=ticker),
    )
    _run_and_report(job_id, job)

    assert _scan_run_statuses(repo, "gex_scan_%") == ["error", "error", "error"]
    assert job_id not in _streaks(repo)


def test_grg_and_discovery_failures_match_scan_runs(
    repo, _migrated_settings, monkeypatch
):
    """One unit each. A failed UW fetch inside the real scanner/job persists an
    'error'/'fail' scan_run AND reaches the streak; a later success clears it."""
    import uw_scan.scanners.grg as grg_scanner
    import uw_scan.sources.uw as uw_source
    import uw_scan.worker.jobs.discovery_scan as discovery_mod

    dsn = _migrated_settings.db_dsn()
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )
    jobs = _capture_uw0_jobs(
        monkeypatch,
        repo,
        {"regime_grg_scan", "discovery_scan"},
        {"SCANNER_DISCOVER_SCAN_ENABLED": "true"},
    )

    def boom(*_a, **_k):
        raise RuntimeError("uw 500")

    monkeypatch.setattr(uw_source, "fetch_greek_exposure_history", boom)
    monkeypatch.setattr(discovery_mod, "fetch_market_flow_alerts", boom)
    for job_id, job in jobs.items():
        _run_and_report(job_id, job)

    assert _scan_run_statuses(repo, "grg_scan") == ["error"]
    assert _scan_run_statuses(repo, "discovery_scan") == ["fail"]
    for job_id in jobs:
        assert _streaks(repo)[job_id].consecutive == 1
        assert "uw 500" in _streaks(repo)[job_id].last_error

    # Success clears each streak: GRG via a stubbed snapshot, discovery via the
    # real job on an empty alert feed (an 'ok' run with zero candidates).
    monkeypatch.setattr(grg_scanner, "run", lambda *a, **k: None)
    monkeypatch.setattr(discovery_mod, "fetch_market_flow_alerts", lambda *a, **k: [])
    for job_id, job in jobs.items():
        _run_and_report(job_id, job)

    assert _scan_run_statuses(repo, "discovery_scan") == ["fail", "ok"]
    assert not set(jobs) & set(_streaks(repo))


def test_top_net_impact_failure_streak_matches_scan_runs_then_success_clears(
    repo, _migrated_settings, monkeypatch
):
    """The real `regime_top_net_impact_scan` closure and scanner, run against
    the test DB: two failed UW fetches -> two 'error' scan_runs and streak 2;
    one good fetch -> an 'ok' scan_run and the streak cleared.

    Before the fix the closure swallowed the error, so the scan_run said
    'error' while the listener recorded a success.
    """
    import uw_scan.sources.uw as uw_source

    dsn = _migrated_settings.db_dsn()
    monkeypatch.setattr(
        scheduler, "_ops_conn", lambda: psycopg.connect(dsn, autocommit=True)
    )
    job_id = "regime_top_net_impact_scan"
    job = _capture_uw0_jobs(
        monkeypatch, repo, {job_id}, {"TOP_NET_IMPACT_CAPTURE_ENABLED": "true"}
    )[job_id]

    def boom(*_a, **_k):
        raise RuntimeError("tni boom")

    monkeypatch.setattr(uw_source, "fetch_top_net_impact", boom)
    _run_and_report(job_id, job)
    _run_and_report(job_id, job)

    assert _scan_run_statuses(repo, job_id) == ["error", "error"]
    assert _streaks(repo)[job_id].consecutive == 2
    assert "tni boom" in _streaks(repo)[job_id].last_error

    # Zero rows published is a normal outcome: an 'ok' run, streak cleared.
    monkeypatch.setattr(uw_source, "fetch_top_net_impact", lambda *a, **k: [])
    _run_and_report(job_id, job)

    assert _scan_run_statuses(repo, job_id) == ["error", "error", "ok"]
    assert job_id not in _streaks(repo)
