from __future__ import annotations

from datetime import date, timedelta

from uw_scan.worker.jobs.vrp_research_jobs import vrp_research_refresh


def _seed_spy(repo, *, n=80):
    d0 = date(2026, 1, 1)
    with repo.conn.cursor() as cur:
        cur.execute(
            f"INSERT INTO {repo._schema}.watchlist (ticker, sector) VALUES ('SPY','Macro') "
            "ON CONFLICT (ticker) DO UPDATE SET sector='Macro', removed_at=NULL"
        )
        for i in range(n):
            d = d0 + timedelta(days=i)
            cur.execute(
                f"INSERT INTO {repo._schema}.realized_volatility_history "
                "(ticker, market_date, price) VALUES ('SPY', %s, %s)",
                (d, 100.0 if i % 2 == 0 else 101.0),
            )
            cur.execute(
                f"INSERT INTO {repo._schema}.vrp_daily "
                "(ticker, market_date, iv, rv, vrp, vrp_z_20) "
                "VALUES ('SPY', %s, %s, %s, %s, %s)",
                (d, 0.30, 0.20, 0.10, 1.5),
            )
    repo.conn.commit()


def test_orchestrator_runs_all_axes_and_persists(seeded_db_empty_cards):
    repo = seeded_db_empty_cards
    _seed_spy(repo)
    results = vrp_research_refresh(repo=repo)
    # all five axes ran without raising
    assert set(results) == {
        "rv_validation",
        "harvest_by_sector",
        "harvest_multihorizon",
        "directional",
        "dvrp_reversion",
    }
    assert all("error" not in v for v in results.values())
    # SPY (index_macro) populates validation + multi-horizon + ΔVRP
    assert repo.fetch_vrp_rv_validation()
    assert repo.fetch_vrp_harvest_multihorizon()
    assert repo.fetch_vrp_dvrp_reversion()


def _boom(*_a, **_k):
    raise RuntimeError("directional boom")


def test_one_failed_axis_keeps_the_others_then_raises(
    seeded_db_empty_cards, monkeypatch
):
    """Unit = one axis. Each axis commits its own table, so the four good axes
    stay persisted; the job then raises so the listener records the failure."""
    import pytest

    import uw_scan.worker.jobs.vrp_research_jobs as jobs_mod

    repo = seeded_db_empty_cards
    _seed_spy(repo)
    monkeypatch.setattr(jobs_mod, "run_vrp_directional", _boom)

    with pytest.raises(RuntimeError, match=r"1/5 axes failed \(directional\)"):
        vrp_research_refresh(repo=repo)

    assert repo.fetch_vrp_rv_validation()
    assert repo.fetch_vrp_harvest_multihorizon()
    assert repo.fetch_vrp_dvrp_reversion()  # ran AFTER the failed axis


def test_failed_axis_reaches_streak_then_success_clears(
    seeded_db_empty_cards, _migrated_settings, monkeypatch
):
    """The real `vrp_research_refresh` closure feeds the job listener: a failed
    axis -> streak 1; a clean run -> streak cleared."""
    from contextlib import contextmanager
    from types import SimpleNamespace

    import psycopg
    import pytest

    import uw_scan.worker.jobs.vrp_research_jobs as jobs_mod
    from uw_scan.storage.ops_health import JobFailuresRepository
    from uw_scan.worker import scheduler

    repo = seeded_db_empty_cards
    _seed_spy(repo)
    job_id = "vrp_research_refresh"
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
    monkeypatch.setenv("UW_SCAN_WORKER_ROLE", "massive")
    monkeypatch.setenv("UW_SCAN_WORKER_INDEX", "0")
    monkeypatch.setenv("UW_SCAN_WORKER_COUNT", "1")
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

    def streaks() -> dict:
        return {s.job_name: s for s in JobFailuresRepository(repo.conn).list_streaks()}

    real_directional = jobs_mod.run_vrp_directional
    monkeypatch.setattr(jobs_mod, "run_vrp_directional", _boom)
    run_and_report()
    assert streaks()[job_id].consecutive == 1
    assert "directional boom" in streaks()[job_id].last_error

    monkeypatch.setattr(jobs_mod, "run_vrp_directional", real_directional)
    run_and_report()
    assert job_id not in streaks()
