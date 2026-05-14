from __future__ import annotations

from datetime import datetime
from contextlib import contextmanager
from zoneinfo import ZoneInfo

from uw_scan.worker.scheduler import (
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
