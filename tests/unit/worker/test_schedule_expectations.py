from __future__ import annotations

from datetime import UTC, datetime

from uw_scan.config import Settings
from uw_scan.worker.market_session import is_us_equity_market_day
from uw_scan.worker.schedule_expectations import (
    expected_market_cron_fires_between,
    latest_expected_market_cron_fire,
)


def test_us_equity_market_day_excludes_memorial_day() -> None:
    assert not is_us_equity_market_day(datetime(2026, 5, 25, tzinfo=UTC).date())


def test_latest_expected_full_scan_skips_memorial_day() -> None:
    settings = Settings(api_key="uw")
    now = datetime(2026, 5, 25, 14, 0, tzinfo=UTC)

    latest = latest_expected_market_cron_fire(
        settings.full_scan_crons,
        settings.rth_tz,
        now_utc=now,
    )

    assert latest == datetime(2026, 5, 22, 20, 30, tzinfo=UTC)


def test_expected_full_scan_misses_skip_market_holiday() -> None:
    settings = Settings(api_key="uw")
    last_scan = datetime(2026, 5, 22, 20, 30, tzinfo=UTC)
    now = datetime(2026, 5, 25, 14, 0, tzinfo=UTC)

    misses = expected_market_cron_fires_between(
        settings.full_scan_crons,
        settings.rth_tz,
        start_utc=last_scan,
        end_utc=now,
    )

    assert misses == []
