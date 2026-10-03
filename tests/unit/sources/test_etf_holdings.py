"""ETF holdings provider — SPDR historical archive (GLD, GLDM), CSV or XLSX."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from io import BytesIO
from unittest.mock import patch

import httpx
from openpyxl import Workbook

from uw_scan.sources.etf_holdings import EtfHoldingRow, EtfHoldingsProvider

GLD_CSV = """Date,Total Net Assets (USD),Tons in the Trust,Ounces in the Trust,NAV per Share (USD)
05/12/2026,75123456789,872.5,28047500.12,234.50
05/13/2026,75500000000,873.0,28063540.00,235.10
"""


def _fake_csv_response(text: str) -> httpx.Response:
    return httpx.Response(
        200,
        text=text,
        request=httpx.Request("GET", EtfHoldingsProvider.SPDR_ARCHIVE_URL),
    )


def _fake_xlsx_response(ticker: str = "GLD") -> httpx.Response:
    wb = Workbook()
    disclaimer = wb.active
    disclaimer.title = "Disclaimer"
    sheet = wb.create_sheet(f"US {ticker} Historical Archive")
    sheet.append(
        [
            "Date",
            "Closing Price",
            "Ounces of Gold per Share",
            "NAV/Share at 10:30am NYT",
            "Indicative Price per Share at 4:15pm NYT",
            "Mid point of bid/ask spread at 4:15pm NYT",
            f"Premium/Discount of {ticker} Mid Point vs Indicative Value of {ticker} at 4:15pm NYT",
            "Daily Share Volume",
            "Total Ounces of Gold in the Trust",
            "Tonnes of Gold",
            "Total Net Asset Value in the Trust",
        ]
    )
    sheet.append(
        [
            "13-May-2026",
            Decimal("235.10"),
            Decimal("0.0931"),
            Decimal("234.90"),
            Decimal("235.00"),
            Decimal("235.10"),
            Decimal("0.04"),
            1_500_000,
            Decimal("28063540.00"),
            Decimal("872.87"),
            Decimal("75500000000"),
        ]
    )
    sheet.append(
        [
            "14-May-2026",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
            "US Holiday",
        ]
    )
    buf = BytesIO()
    wb.save(buf)
    return httpx.Response(
        200,
        content=buf.getvalue(),
        request=httpx.Request("GET", EtfHoldingsProvider.SPDR_ARCHIVE_URL),
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


def test_etf_provider_parses_spdr_historical_archive_xlsx():
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_xlsx_response()
        with EtfHoldingsProvider() as p:
            rows = p.fetch_gld(start=date(2026, 5, 12))
    assert mock_get.call_args.args[1] == {
        "product": "gld",
        "exchange": "NYSE",
        "lang": "en",
    }
    assert rows == [
        EtfHoldingRow(
            ticker="GLD",
            obs_date=date(2026, 5, 13),
            holdings_oz=Decimal("28063540.00"),
            shares_out=None,
            nav_per_share=Decimal("234.90"),
            premium_pct=Decimal("0.04"),
        )
    ]


def test_etf_provider_gldm_reads_the_same_spdr_archive():
    # The old historical-data-gldm/ page 404s; GLDM is product=gldm on the GLD API.
    with patch.object(EtfHoldingsProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_xlsx_response("GLDM")
        with EtfHoldingsProvider() as p:
            rows = p.fetch_gldm(start=date(2026, 5, 12))
    assert mock_get.call_args.args[1]["product"] == "gldm"
    assert mock_get.call_args.kwargs["endpoint_key"] == "spdr_gldm_archive"
    assert [(r.ticker, r.holdings_oz, r.premium_pct) for r in rows] == [
        ("GLDM", Decimal("28063540.00"), Decimal("0.04"))
    ]
