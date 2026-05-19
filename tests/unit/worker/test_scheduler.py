from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from apscheduler.triggers.cron import CronTrigger
from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.worker.scheduler import (
    RESCAN_WORKER_CONCURRENCY,
    _ohlc_provider,
    _record_worker_heartbeat,
    _spot_refresh_market_date,
    _uw_auto_request_allowed,
    _worker_heartbeat_name,
)


def test_spot_refresh_market_date_skips_after_hours() -> None:
    now = datetime(2026, 5, 13, 20, 54, tzinfo=ZoneInfo("America/New_York"))

    assert _spot_refresh_market_date(now) is None


def test_spot_refresh_market_date_allows_delayed_after_hours() -> None:
    now = datetime(2026, 5, 13, 19, 59, tzinfo=ZoneInfo("America/New_York"))

    assert _spot_refresh_market_date(now).isoformat() == "2026-05-13"


def test_spot_refresh_market_date_uses_rth_date() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert _spot_refresh_market_date(now).isoformat() == "2026-05-13"


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
