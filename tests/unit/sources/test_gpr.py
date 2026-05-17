"""GPR daily index parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.gpr import GprProvider

SAMPLE_CSV = """date,GPRD
2026-05-12,118.4
2026-05-13,121.2
2026-05-14,
2026-05-15,109.7
"""


def _fake_response(text: str = SAMPLE_CSV, status: int = 200) -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("GET", GprProvider.DEFAULT_URL),
    )


def test_gpr_parses_csv_skips_blank_rows():
    with patch.object(GprProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with GprProvider() as p:
            rows = p.fetch_daily(start=date(2026, 5, 12))
    assert {r.obs_date for r in rows} == {
        date(2026, 5, 12),
        date(2026, 5, 13),
        date(2026, 5, 15),
    }
    assert rows[0].value == Decimal("118.4")


def test_gpr_telemetry_records():
    captured = []

    def fake_record(_self, event):
        captured.append(event)

    with (
        patch.object(GprProvider, "_record_request", fake_record),
        patch("uw_scan.sources.gpr.httpx.Client.get") as mock_get,
    ):
        mock_get.return_value = _fake_response()
        with GprProvider() as p:
            p.fetch_daily(start=date(2026, 5, 12))

    assert len(captured) == 1
    event = captured[0]
    assert event.provider == "gpr"
    assert event.endpoint_key == "gpr_daily_csv"
    assert event.status_code == 200
    assert event.status_family == "2xx"
