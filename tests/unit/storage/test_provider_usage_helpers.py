from __future__ import annotations

from datetime import UTC, datetime

from uw_scan.storage.repository import (
    provider_day_bounds,
    redact_params,
    status_family_for,
)


def test_provider_day_bounds_uses_previous_8pm_et_before_reset():
    now = datetime(2026, 5, 14, 23, 59, tzinfo=UTC)

    start, end = provider_day_bounds(now)

    assert start.isoformat() == "2026-05-13T20:00:00-04:00"
    assert end.isoformat() == "2026-05-14T20:00:00-04:00"


def test_provider_day_bounds_uses_same_day_8pm_et_after_reset():
    now = datetime(2026, 5, 15, 0, 1, tzinfo=UTC)

    start, end = provider_day_bounds(now)

    assert start.isoformat() == "2026-05-14T20:00:00-04:00"
    assert end.isoformat() == "2026-05-15T20:00:00-04:00"


def test_status_family_for_http_statuses_and_transport_errors():
    assert status_family_for(200) == "2xx"
    assert status_family_for(302) == "3xx"
    assert status_family_for(404) == "4xx"
    assert status_family_for(503) == "5xx"
    assert status_family_for(None, transport_error=True) == "transport_error"


def test_redact_params_drops_auth_keys_and_truncates_long_values():
    params = {
        "ticker": "TSLA",
        "api_key": "secret",
        "Authorization": "Bearer secret",
        "notes": "x" * 300,
        "limit": 100,
    }

    redacted = redact_params(params)

    assert redacted["ticker"] == "TSLA"
    assert redacted["limit"] == 100
    assert "api_key" not in redacted
    assert "Authorization" not in redacted
    assert redacted["notes"] == ("x" * 253) + "..."
