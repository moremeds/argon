"""ETF holdings provider — GLD CSV, IAU JSON, PHYS JSON."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.etf_holdings import EtfHoldingRow, EtfHoldingsProvider

GLD_CSV = """Date,Total Net Assets (USD),Tons in the Trust,Ounces in the Trust,NAV per Share (USD)
05/12/2026,75123456789,872.5,28047500.12,234.50
05/13/2026,75500000000,873.0,28063540.00,235.10
"""


def _fake_csv_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=text,
        request=httpx.Request("GET", EtfHoldingsProvider.GLD_URL),
    )


def _fake_json_response(payload: dict, url: str) -> httpx.Response:
    return httpx.Response(
        200,
        json=payload,
        request=httpx.Request("GET", url),
    )


def test_etf_provider_parses_gld_csv():
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_csv_response(GLD_CSV)
        with EtfHoldingsProvider() as p:
            rows = p.fetch_gld(start=date(2026, 5, 12))
    assert len(rows) == 2
    assert rows[0] == EtfHoldingRow(
        ticker="GLD",
        obs_date=date(2026, 5, 12),
        holdings_oz=Decimal("28047500.12"),
        shares_out=None,
        nav_per_share=Decimal("234.50"),
        premium_pct=None,
    )


def test_etf_provider_iau_uses_blackrock_endpoint():
    iau_json = {
        "data": [
            {
                "asOfDate": "2026-05-12",
                "totalAssets": 12345.6,
                "navPerShare": 47.50,
                "physicalGoldOunces": 8500000.0,
            },
        ]
    }
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_json_response(
            iau_json, EtfHoldingsProvider.IAU_URL
        )
        with EtfHoldingsProvider() as p:
            rows = p.fetch_iau(start=date(2026, 5, 12))
    assert rows[0].ticker == "IAU"
    assert rows[0].holdings_oz == Decimal("8500000.0")
    assert rows[0].nav_per_share == Decimal("47.5")


def test_etf_provider_phys_captures_premium():
    phys_json = {
        "data": [
            {
                "date": "2026-05-13",
                "nav": 18.21,
                "goldOunces": 1654321.5,
                "premiumDiscountPct": -1.42,
            }
        ]
    }
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_json_response(
            phys_json, EtfHoldingsProvider.PHYS_URL
        )
        with EtfHoldingsProvider() as p:
            rows = p.fetch_phys(start=date(2026, 5, 13))
    assert rows[0].ticker == "PHYS"
    assert rows[0].premium_pct == Decimal("-1.42")
