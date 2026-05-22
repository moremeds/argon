from __future__ import annotations

from datetime import date
from unittest.mock import patch

import httpx

from uw_scan.sources.cme_fedwatch import CmeFedWatchProvider


def test_cme_fedwatch_provider_normalizes_official_forecast_payload() -> None:
    payload = {
        "tradeDate": "2026-05-22",
        "meetings": [
            {
                "meetingDate": "2026-06-17",
                "probabilities": [
                    {"targetRate": "350-375", "probability": 99.0},
                    {"targetRate": "375-400", "probability": 1.0},
                ],
            }
        ],
    }
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "/forecasts/latest"),
    )

    with patch.object(CmeFedWatchProvider, "_get", return_value=response):
        with CmeFedWatchProvider(api_token="token", application_name="uw-scan") as provider:
            rows = provider.fetch_latest_path(current_target_range="3.50-3.75%")

    assert rows[0].meeting_date == date(2026, 6, 17)
    assert rows[0].target_range == "3.50-3.75%"
    assert rows[0].probability == 99.0
    assert rows[0].stance == "HOLD"


def test_cme_fedwatch_provider_accepts_documented_rate_range_shape() -> None:
    payload = {
        "data": [
            {
                "meetingDt": "2026-06-17",
                "rateRange": [
                    {"lowerRt": 350, "upperRt": 375, "probability": 98.5},
                    {"lowerRt": 375, "upperRt": 400, "probability": 1.5},
                ],
            }
        ],
    }
    response = httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", "/forecasts/latest"),
    )

    with patch.object(CmeFedWatchProvider, "_get", return_value=response):
        with CmeFedWatchProvider(api_token="token", application_name="uw-scan") as provider:
            rows = provider.fetch_latest_path(current_target_range="3.50-3.75%")

    assert rows[0].meeting_date == date(2026, 6, 17)
    assert rows[0].target_range == "3.50-3.75%"
    assert rows[0].probability == 98.5
    assert rows[0].stance == "HOLD"
