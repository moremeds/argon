from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.worker.market_session import current_market_date
from uw_scan.worker.scheduler import (
    RESCAN_WORKER_CONCURRENCY,
    _ohlc_provider,
    _record_worker_heartbeat,
    _run_rates_fred_ingest,
    _should_schedule_macro_policy_ingest,
    _should_schedule_pipeline_benchmark,
    _should_schedule_rates_fred_ingest,
    _should_schedule_skew_swing_greeks,
    _uw_auto_request_allowed,
    _worker_heartbeat_name,
)


def test_current_market_date_skips_after_hours() -> None:
    """20:54 ET is after the 04:00-20:00 feed-active window."""
    now = datetime(2026, 5, 13, 20, 54, tzinfo=ZoneInfo("America/New_York"))

    assert current_market_date(now) is None


def test_current_market_date_allows_after_hours() -> None:
    """19:59 ET is inside the post-close after-hours session."""
    now = datetime(2026, 5, 13, 19, 59, tzinfo=ZoneInfo("America/New_York"))

    assert current_market_date(now).isoformat() == "2026-05-13"


def test_current_market_date_allows_pre_market() -> None:
    """04:00 ET is the lower bound of massive.com's feed-active window."""
    now = datetime(2026, 5, 13, 6, 30, tzinfo=ZoneInfo("America/New_York"))

    assert current_market_date(now).isoformat() == "2026-05-13"


def test_current_market_date_uses_rth_date() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert current_market_date(now).isoformat() == "2026-05-13"


def test_current_market_date_skips_market_holidays() -> None:
    now = datetime(2026, 5, 25, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert current_market_date(now) is None


def test_uw_auto_request_allowed_starts_at_5am_et() -> None:
    before_window = datetime(2026, 5, 13, 4, 59, tzinfo=ZoneInfo("America/New_York"))
    start = datetime(2026, 5, 13, 5, 0, tzinfo=ZoneInfo("America/New_York"))

    assert _uw_auto_request_allowed(before_window) is False
    assert _uw_auto_request_allowed(start) is True


def test_uw_auto_request_allowed_stops_before_overnight() -> None:
    evening = datetime(2026, 5, 13, 19, 59, tzinfo=ZoneInfo("America/New_York"))
    overnight = datetime(2026, 5, 13, 20, 0, tzinfo=ZoneInfo("America/New_York"))

    assert _uw_auto_request_allowed(evening) is True
    assert _uw_auto_request_allowed(overnight) is False


def test_uw_auto_request_allowed_skips_weekends() -> None:
    saturday = datetime(2026, 5, 16, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert _uw_auto_request_allowed(saturday) is False


def test_record_worker_heartbeat_uses_dedicated_worker_key(monkeypatch) -> None:
    calls: list[str] = []

    class Repo:
        def upsert_heartbeat(self, job_name: str) -> None:
            calls.append(job_name)

    @contextmanager
    def fake_repo(_settings):
        yield Repo()

    monkeypatch.setattr("uw_scan.worker.scheduler._repo", fake_repo)

    _record_worker_heartbeat(Settings(api_key="uw"))

    assert calls == ["worker"]


def test_record_worker_heartbeat_uses_provider_worker_key(monkeypatch) -> None:
    calls: list[str] = []

    class Repo:
        def upsert_heartbeat(self, job_name: str) -> None:
            calls.append(job_name)

    @contextmanager
    def fake_repo(_settings):
        yield Repo()

    monkeypatch.setattr("uw_scan.worker.scheduler._repo", fake_repo)

    settings = Settings(
        api_key="uw", worker_role="massive", worker_index=1, worker_count=2
    )
    _record_worker_heartbeat(settings)

    assert calls == ["worker:massive:1"]


def test_worker_heartbeat_name_keeps_legacy_all_worker() -> None:
    assert _worker_heartbeat_name(Settings(api_key="uw")) == "worker"


def test_ohlc_provider_uses_configured_request_timeout(monkeypatch) -> None:
    captured: dict[str, object] = {}

    class FakeProvider:
        def __init__(self, **kwargs) -> None:
            captured.update(kwargs)

    monkeypatch.setattr("uw_scan.worker.scheduler.MassiveOhlcProvider", FakeProvider)

    settings = Settings(
        api_key="uw",
        massive_api_key=SecretStr("massive"),
        request_timeout_seconds=42.0,
    )

    provider = _ohlc_provider(settings)

    assert provider is not None
    assert captured["timeout"] == 42.0


def test_rates_fred_ingest_helper_uses_unwrapped_key_and_recorder(monkeypatch) -> None:
    calls: list[dict[str, object]] = []
    recorded: list[object] = []

    class Recorder:
        def record(self, event: object) -> None:
            recorded.append(event)

    @contextmanager
    def fake_recorder(_settings):
        yield Recorder()

    def fake_job(**kwargs) -> None:
        calls.append(kwargs)
        kwargs["record_request"]("fred", {"params": {"series_id": "DGS10"}})

    monkeypatch.setattr(
        "uw_scan.worker.scheduler._external_api_recorder", fake_recorder
    )
    monkeypatch.setattr("uw_scan.worker.scheduler.rates_fred_ingest_job", fake_job)

    settings = Settings(api_key="uw", fred_api_key=SecretStr("fred-secret"))

    _run_rates_fred_ingest(settings)

    assert len(calls) == 1
    assert calls[0]["dsn"] == settings.db_dsn()
    assert calls[0]["schema"] == settings.db_schema
    assert calls[0]["fred_api_key"] == "fred-secret"
    assert recorded == [{"params": {"series_id": "DGS10"}}]


def test_rates_fred_ingest_helper_skips_when_key_missing(monkeypatch) -> None:
    calls: list[dict[str, object]] = []

    def fake_job(**kwargs) -> None:
        calls.append(kwargs)

    monkeypatch.setattr("uw_scan.worker.scheduler.rates_fred_ingest_job", fake_job)

    _run_rates_fred_ingest(Settings(api_key="uw", fred_api_key=None))

    assert calls == []


def test_rates_fred_ingest_schedules_only_on_all_or_primary_uw_worker() -> None:
    assert _should_schedule_rates_fred_ingest(Settings(api_key="uw", worker_role="all"))
    assert _should_schedule_rates_fred_ingest(
        Settings(api_key="uw", worker_role="uw", worker_index=0, worker_count=3)
    )
    assert not _should_schedule_rates_fred_ingest(
        Settings(api_key="uw", worker_role="uw", worker_index=1, worker_count=3)
    )
    assert not _should_schedule_rates_fred_ingest(
        Settings(api_key="uw", worker_role="massive", worker_index=0, worker_count=1)
    )
    assert not _should_schedule_rates_fred_ingest(
        Settings(api_key="uw", worker_role="ai", worker_index=0, worker_count=1)
    )


def test_macro_policy_ingest_has_one_non_uw_owner() -> None:
    assert _should_schedule_macro_policy_ingest(
        Settings(api_key="uw", worker_role="all")
    )
    assert _should_schedule_macro_policy_ingest(
        Settings(api_key="uw", worker_role="massive", worker_index=0, worker_count=2)
    )
    assert not _should_schedule_macro_policy_ingest(
        Settings(api_key="uw", worker_role="massive", worker_index=1, worker_count=2)
    )
    assert not _should_schedule_macro_policy_ingest(
        Settings(api_key="uw", worker_role="uw", worker_index=0, worker_count=2)
    )


def test_skew_swing_greeks_schedules_only_on_all_or_primary_uw_worker() -> None:
    # Must NOT use _is_primary_worker (true for index-0 of EVERY role) — that would
    # run the lock-less UW loop in ~5 processes (duplicate spend + racing writes).
    assert _should_schedule_skew_swing_greeks(Settings(api_key="uw", worker_role="all"))
    assert _should_schedule_skew_swing_greeks(
        Settings(api_key="uw", worker_role="uw", worker_index=0, worker_count=3)
    )
    assert not _should_schedule_skew_swing_greeks(
        Settings(api_key="uw", worker_role="uw", worker_index=1, worker_count=3)
    )
    # index-0 of other roles must be excluded (this is the bug being fixed).
    assert not _should_schedule_skew_swing_greeks(
        Settings(api_key="uw", worker_role="massive", worker_index=0, worker_count=1)
    )
    assert not _should_schedule_skew_swing_greeks(
        Settings(api_key="uw", worker_role="ai-codex", worker_index=0, worker_count=1)
    )


def test_pipeline_benchmark_schedules_only_on_all_or_primary_uw_worker() -> None:
    assert _should_schedule_pipeline_benchmark(
        Settings(api_key="uw", worker_role="all")
    )
    assert _should_schedule_pipeline_benchmark(
        Settings(api_key="uw", worker_role="uw", worker_index=0, worker_count=3)
    )
    assert not _should_schedule_pipeline_benchmark(
        Settings(api_key="uw", worker_role="uw", worker_index=1, worker_count=3)
    )
    assert not _should_schedule_pipeline_benchmark(
        Settings(api_key="uw", worker_role="massive", worker_index=0, worker_count=1)
    )
    assert not _should_schedule_pipeline_benchmark(
        Settings(api_key="uw", worker_role="ai-codex", worker_index=0, worker_count=1)
    )
    assert not _should_schedule_pipeline_benchmark(
        Settings(api_key="uw", worker_role="ai-claude", worker_index=0, worker_count=1)
    )


def test_rescan_worker_concurrency_is_two() -> None:
    assert RESCAN_WORKER_CONCURRENCY == 2


def test_default_weekday_crons_include_monday_et() -> None:
    settings = Settings(api_key="uw")
    # Anchor before the earliest cron (04:00 ET premarket warm-up) so every
    # cron's "next fire" lands on the same Monday, including the 4am scan.
    monday_et = datetime(2026, 5, 18, 3, 0, tzinfo=ZoneInfo(settings.rth_tz))

    for expr in (
        *settings.full_scan_crons,
        settings.ohlc_pull_cron,
        settings.cockpit_snapshot_cron,
    ):
        trigger = CronTrigger.from_crontab(expr, timezone=settings.rth_tz)
        next_fire = trigger.get_next_fire_time(None, monday_et)

        assert next_fire is not None
        assert next_fire.weekday() == 0
        assert next_fire.date() == monday_et.date()


def test_scheduler_cron_literals_do_not_use_apscheduler_tuesday_to_saturday_range() -> (
    None
):
    repo_root = Path(__file__).resolve().parents[3]
    production_sources = (
        repo_root / "src/uw_scan/config.py",
        repo_root / "src/uw_scan/worker/scheduler.py",
    )

    offenders = [
        str(path.relative_to(repo_root))
        for path in production_sources
        if "* * 1-5" in path.read_text()
    ]

    assert offenders == []


def _listener_spy(monkeypatch):
    """Route _handle_job_event's DB writes to an in-memory call log."""
    from contextlib import nullcontext
    from types import SimpleNamespace

    import uw_scan.storage.ops_health as ops_health
    import uw_scan.worker.scheduler as scheduler

    calls: list[tuple[str, str]] = []

    class _FakeRepo:
        def __init__(self, _conn) -> None:
            pass

        def record_success(self, job_name: str) -> None:
            calls.append(("success", job_name))

        def record_failure(self, job_name: str, _error: str) -> None:
            calls.append(("failure", job_name))

        def list_streaks(self):
            return []

    monkeypatch.setattr(
        scheduler,
        "_ops_conn",
        lambda: nullcontext(SimpleNamespace(commit=lambda: None)),
    )
    monkeypatch.setattr(ops_health, "JobFailuresRepository", _FakeRepo)
    monkeypatch.setattr(scheduler, "_tick_jobs_recorded_clean", set())
    return scheduler, calls


def test_job_listener_skips_repeat_tick_job_successes(monkeypatch) -> None:
    from types import SimpleNamespace

    scheduler, calls = _listener_spy(monkeypatch)
    ok = SimpleNamespace(job_id="worker_heartbeat", exception=None)

    for _ in range(5):
        scheduler._handle_job_event(ok)

    # Only the first success of the process is written (clears any streak a
    # previous process left behind); the other four open no connection.
    assert calls == [("success", "worker_heartbeat")]


def test_job_listener_records_tick_failure_and_the_success_that_resets_it(
    monkeypatch,
) -> None:
    from types import SimpleNamespace

    scheduler, calls = _listener_spy(monkeypatch)
    ok = SimpleNamespace(job_id="rescan_tick", exception=None)
    boom = SimpleNamespace(job_id="rescan_tick", exception=RuntimeError("boom"))

    for event in (ok, ok, boom, boom, ok, ok):
        scheduler._handle_job_event(event)

    assert calls == [
        ("success", "rescan_tick"),
        ("failure", "rescan_tick"),
        ("failure", "rescan_tick"),
        ("success", "rescan_tick"),
    ]


def test_job_listener_records_every_non_tick_success(monkeypatch) -> None:
    from types import SimpleNamespace

    scheduler, calls = _listener_spy(monkeypatch)
    ok = SimpleNamespace(job_id="full_scan", exception=None)

    scheduler._handle_job_event(ok)
    scheduler._handle_job_event(ok)

    assert calls == [("success", "full_scan"), ("success", "full_scan")]


def test_tick_job_ids_match_registered_interval_jobs() -> None:
    import uw_scan.worker.scheduler as scheduler

    source = Path(scheduler.__file__).read_text()
    for job_id in scheduler._TICK_JOB_IDS:
        assert f'id="{job_id}"' in source, job_id
