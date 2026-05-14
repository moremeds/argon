from __future__ import annotations

from datetime import datetime
from zoneinfo import ZoneInfo

from uw_scan.worker.scheduler import _spot_refresh_market_date


def test_spot_refresh_market_date_skips_after_hours() -> None:
    now = datetime(2026, 5, 13, 20, 54, tzinfo=ZoneInfo("America/New_York"))

    assert _spot_refresh_market_date(now) is None


def test_spot_refresh_market_date_uses_rth_date() -> None:
    now = datetime(2026, 5, 13, 10, 0, tzinfo=ZoneInfo("America/New_York"))

    assert _spot_refresh_market_date(now).isoformat() == "2026-05-13"
