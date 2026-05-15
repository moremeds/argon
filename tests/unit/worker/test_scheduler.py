from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime
from zoneinfo import ZoneInfo

from pydantic import SecretStr

from uw_scan.config import Settings
from uw_scan.worker.scheduler import (
    RESCAN_WORKER_CONCURRENCY,
    _ohlc_provider,
    _record_worker_heartbeat,
    _spot_refresh_market_date,
    _uw_auto_request_allowed,
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

    _record_worker_heartbeat(object())

    assert calls == ["worker"]


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
