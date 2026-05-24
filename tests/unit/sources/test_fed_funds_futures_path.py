from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx

from uw_scan.sources.fed_funds_futures_path import FedFundsFuturesPathProvider


FED_WATCH_HTML = """
<script>window.__SSR_DATA__ = {"current_effr": 3.67, "current_rate": 3.75, "meetings": [{"change_bps": -11.54, "contract": "/ZQM26", "implied_avg_effr": 3.62, "meeting_date": "2026-06-17", "post_rate": 3.5546, "pre_rate": 3.67, "probabilities": {"cut_25": 0.4615, "cut_gt25": 0.0, "hike_25": 0.0, "hike_gt25": 0.0, "hold": 0.5385}}, {"change_bps": 11.54, "contract": "/ZQN26", "implied_avg_effr": 3.635, "meeting_date": "2026-07-29", "post_rate": 3.67, "pre_rate": 3.5546, "probabilities": {"cut_25": 0.0, "cut_gt25": 0.0, "hike_25": 0.4615, "hike_gt25": 0.0, "hold": 0.5385}}], "next_meeting": "2026-06-17"};</script>
"""


def test_fed_funds_futures_path_provider_parses_move_probability_rows() -> None:
    response = httpx.Response(
        200,
        text=FED_WATCH_HTML,
        request=httpx.Request("GET", "https://www.frenzycap.com/fedwatch"),
    )

    with patch.object(FedFundsFuturesPathProvider, "_get", return_value=response):
        with FedFundsFuturesPathProvider() as provider:
            rows = provider.fetch_latest_path(current_target_range="3.50-3.75%")

    assert len(rows) == 2
    assert rows[0].meeting_date == date(2026, 6, 17)
    assert rows[0].label == "6/17"
    assert rows[0].probability == 53.9
    assert rows[0].stance == "HOLD"
    assert rows[0].target_range == "3.50-3.75%"
    assert rows[0].source == "Frenzy Capital Fed Watch"

    assert rows[1].meeting_date == date(2026, 7, 29)
    assert rows[1].probability == 53.9
    assert rows[1].stance == "HOLD"
    assert rows[1].target_range == "3.50-3.75%"


def test_fed_funds_futures_path_provider_rejects_empty_parse() -> None:
    response = httpx.Response(
        200,
        text="<html><body>shape changed</body></html>",
        request=httpx.Request("GET", "https://www.frenzycap.com/fedwatch"),
    )

    with patch.object(FedFundsFuturesPathProvider, "_get", return_value=response):
        with FedFundsFuturesPathProvider() as provider:
            try:
                provider.fetch_latest_path(current_target_range="3.50-3.75%")
            except ValueError as exc:
                assert "meeting rows" in str(exc)
            else:
                raise AssertionError("empty FedWatch parse should fail the source")
