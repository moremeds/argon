"""FRED CSV client — parses fredgraph.csv and returns typed rows."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.fred import FredObservation, FredProvider

SAMPLE_CSV = """observation_date,DFII10
2026-05-12,1.95
2026-05-13,1.97
2026-05-14,.
2026-05-15,2.01
"""


def _fake_response(status: int = 200, text: str = SAMPLE_CSV) -> httpx.Response:
    return httpx.Response(
        status,
        text=text,
        request=httpx.Request("GET", "https://fred.stlouisfed.org/graph/fredgraph.csv"),
    )


def test_fred_parses_csv_skips_missing():
    """CSV rows with '.' are missing observations and must be skipped."""
    with patch.object(FredProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with FredProvider() as p:
            rows = p.fetch_series("DFII10", start=date(2026, 5, 12))
    assert len(rows) == 3
    assert rows[0] == FredObservation(
        series_id="DFII10",
        obs_date=date(2026, 5, 12),
        value=Decimal("1.95"),
    )
    assert all(r.value is not None for r in rows)


def test_fred_filters_by_start_date():
    with patch.object(FredProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with FredProvider() as p:
            rows = p.fetch_series("DFII10", start=date(2026, 5, 14))
    assert all(r.obs_date >= date(2026, 5, 14) for r in rows)
    assert {r.obs_date for r in rows} == {date(2026, 5, 15)}


def test_fred_telemetry_records_request():
    captured = []

    def fake_record(_self, event):
        captured.append(event)

    with (
        patch.object(FredProvider, "_record_request", fake_record),
        patch("uw_scan.sources.fred.httpx.Client.get") as mock_get,
    ):
        mock_get.return_value = httpx.Response(
            200,
            text=SAMPLE_CSV,
            request=httpx.Request(
                "GET", "https://fred.stlouisfed.org/graph/fredgraph.csv"
            ),
        )
        with FredProvider() as p:
            p.fetch_series("DFII10", start=date(2026, 5, 12))

    assert len(captured) == 1
    event = captured[0]
    assert event.provider == "fred"
    assert event.endpoint_key == "fred_csv"
    assert event.path == "/graph/fredgraph.csv"
    assert event.status_code == 200
    assert event.status_family == "2xx"
    assert event.method == "GET"
    assert event.error_message is None
    assert event.latency_ms >= 0
