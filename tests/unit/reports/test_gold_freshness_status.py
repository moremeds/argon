"""Gold freshness labels follow ingest age (I-113).

The label used to be "ok" whenever ANY row existed: WGC read "ok" at 137 days old.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from uw_scan.models.gold import GoldDataFreshnessSource
from uw_scan.reports.gold_posture import _freshness_status

NOW = datetime(2026, 10, 3, 12, tzinfo=UTC)


def test_wgc_at_137_days_is_stale_not_ok():
    assert _freshness_status("WGC", NOW - timedelta(days=137), NOW) == "stale"
    assert _freshness_status("WGC", NOW - timedelta(days=60), NOW) == "ok"


def test_daily_feed_survives_a_long_weekend_but_not_a_week():
    assert _freshness_status("FRED", NOW - timedelta(days=3, hours=20), NOW) == "ok"
    assert _freshness_status("FRED", NOW - timedelta(days=5), NOW) == "stale"


def test_no_rows_is_missing():
    assert _freshness_status("COMEX", None, NOW) == "missing"


def test_the_api_model_accepts_stale():
    # The router builds this model inside `except ValueError`; a rejected "stale"
    # would silently drop the row from the chip instead of flagging it.
    assert GoldDataFreshnessSource(id="WGC", status="stale").status == "stale"
