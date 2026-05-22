from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.cleveland_fed import (
    ClevelandFedInflationProvider,
    ClevelandFedInflationRecord,
)


CHART1_CSV = """date,expected_inflation,real_risk_premium,inflation_risk_premium
2026-04-01,2.4187847,1.1919907,0.29203643
2026-05-01,2.4761367,1.2312081,0.3489275
"""

CHART2_CSV = """date,tips_yield,model_yield
2026-04-01,2.0438,1.5938719127026608
2026-05-01,1.9507,1.6340507389933305
"""


def _response(path: str, text: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=text,
        request=httpx.Request("GET", f"https://www.clevelandfed.org{path}"),
    )


def test_cleveland_fed_parses_four_component_model_rows() -> None:
    responses = [
        _response(ClevelandFedInflationProvider.CHART1_PATH, CHART1_CSV),
        _response(ClevelandFedInflationProvider.CHART2_PATH, CHART2_CSV),
    ]
    with patch.object(
        ClevelandFedInflationProvider, "_get_with_telemetry", side_effect=responses
    ):
        with ClevelandFedInflationProvider() as provider:
            rows = provider.fetch_model_rows(start=date(2026, 5, 1))

    assert rows == [
        ClevelandFedInflationRecord(
            obs_date=date(2026, 5, 1),
            expected_inflation_10y=Decimal("2.4761367"),
            real_risk_premium_10y=Decimal("1.2312081"),
            inflation_risk_premium_10y=Decimal("0.3489275"),
            model_real_yield_10y=Decimal("1.6340507389933305"),
        )
    ]


def test_cleveland_fed_flattens_model_rows_into_persistable_series() -> None:
    record = ClevelandFedInflationRecord(
        obs_date=date(2026, 5, 1),
        expected_inflation_10y=Decimal("2.4761367"),
        real_risk_premium_10y=Decimal("1.2312081"),
        inflation_risk_premium_10y=Decimal("0.3489275"),
        model_real_yield_10y=Decimal("1.6340507389933305"),
    )

    series_rows = record.to_observation_rows()

    assert {row["series_id"] for row in series_rows} == {
        "CLEVE_EXPECTED_INFLATION_10Y",
        "CLEVE_REAL_RISK_PREMIUM_10Y",
        "CLEVE_INFLATION_RISK_PREMIUM_10Y",
        "CLEVE_MODEL_REAL_YIELD_10Y",
    }
    assert all(row["obs_date"] == date(2026, 5, 1) for row in series_rows)
    assert all(row["source_url"].startswith("https://www.clevelandfed.org") for row in series_rows)
