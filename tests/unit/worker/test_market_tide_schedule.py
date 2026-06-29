from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from uw_scan.config import Settings
from uw_scan.worker.scheduler import (
    _market_tide_cron_trigger,
    _top_net_impact_cron_trigger,
)


def _fires(trigger, day: datetime) -> list[datetime]:
    start = day.replace(hour=0, minute=0, second=0, microsecond=0)
    end = start + timedelta(days=1)
    out = []
    prev = None
    cur = trigger.get_next_fire_time(prev, start - timedelta(seconds=1))
    while cur is not None and cur < end:
        out.append(cur)
        prev = cur
        cur = trigger.get_next_fire_time(prev, prev)
    return out


def _settings(monkeypatch, tmp_path) -> Settings:
    env = tmp_path / "empty.env"
    env.write_text("")
    monkeypatch.setenv("UW_SCAN_API_KEY", "x")
    monkeypatch.setenv("UW_SCAN_DB_HOST", "127.0.0.1")
    monkeypatch.setenv("UW_SCAN_DB_NAME", "option_wizard_local")
    return Settings.from_env(env_path=env)


def test_market_tide_cron_is_0930_to_1610_et(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    fires = _fires(
        _market_tide_cron_trigger(settings),
        datetime(2026, 6, 26, tzinfo=ZoneInfo(settings.rth_tz)),
    )

    assert len(fires) == 81
    assert fires[0].hour == 9 and fires[0].minute == 30
    assert fires[-1].hour == 16 and fires[-1].minute == 10
    assert all(not (f.hour == 9 and f.minute < 30) for f in fires)
    assert all(not (f.hour == 16 and f.minute > 10) for f in fires)


def test_top_net_impact_cron_skips_preopen_noise(monkeypatch, tmp_path):
    settings = _settings(monkeypatch, tmp_path)
    fires = _fires(
        _top_net_impact_cron_trigger(settings),
        datetime(2026, 6, 26, tzinfo=ZoneInfo(settings.rth_tz)),
    )

    assert len(fires) == 28
    assert fires[0].hour == 9 and fires[0].minute == 30
    assert fires[-1].hour == 16 and fires[-1].minute == 15
    assert all(not (f.hour == 9 and f.minute < 30) for f in fires)
    assert all(not (f.hour == 16 and f.minute > 15) for f in fires)
