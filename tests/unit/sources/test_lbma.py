"""LBMA monthly vault parser — xlsx scraped from the listing page."""

from __future__ import annotations

import io
from datetime import date, datetime
from decimal import Decimal
from unittest.mock import patch

import httpx
from openpyxl import Workbook

from uw_scan.sources.lbma import LbmaProvider, LbmaVaultRow

LISTING_HTML = """<html><body>
<a href="https://cdn.lbma.org.uk/downloads/LBMA-London-Vault-Holdings-Data-April-2026.xlsx">April 2026</a>
<a href="https://cdn.lbma.org.uk/downloads/LBMA-London-Vault-Holdings-Data-March-2026.xlsx">March 2026</a>
</body></html>"""


def _build_workbook_bytes() -> bytes:
    """Build a minimal xlsx mirroring the real LBMA file's first sheet layout."""
    wb = Workbook()
    ws = wb.active
    ws.title = "London Vault Holdings Data"
    ws.append(["London Vault Holdings Data", None, None])
    ws.append(["Month End", "Gold", "Silver"])
    ws.append([None, "Troy Ounces ('000s)", "Troy Ounces ('000s)"])
    ws.append(["2026-04", 301320, 882655])
    ws.append([datetime(2026, 3, 1), 300260, 880100])
    ws.append([datetime(2026, 2, 1), 296095.74, 875000])
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def _listing_response() -> httpx.Response:
    return httpx.Response(
        200,
        text=LISTING_HTML,
        request=httpx.Request("GET", LbmaProvider.LISTING_URL),
    )


def _xlsx_response() -> httpx.Response:
    return httpx.Response(
        200,
        content=_build_workbook_bytes(),
        request=httpx.Request(
            "GET",
            "https://cdn.lbma.org.uk/downloads/LBMA-London-Vault-Holdings-Data-April-2026.xlsx",
        ),
    )


def test_lbma_scrapes_listing_then_parses_xlsx() -> None:
    responses = [_listing_response(), _xlsx_response()]
    with patch.object(LbmaProvider, "_get_with_telemetry", side_effect=responses):
        with LbmaProvider() as p:
            rows = p.fetch_monthly(start=date(2026, 2, 1))
    assert len(rows) == 3
    assert rows[0] == LbmaVaultRow(
        obs_date=date(2026, 4, 1),
        vault_oz=Decimal("301320") * Decimal(1000),
    )
    assert rows[1].obs_date == date(2026, 3, 1)
    # 296095.74 thousand oz * 1000 = 296_095_740 oz, fractional preserved.
    assert rows[2].vault_oz == Decimal("296095.74") * Decimal(1000)


def test_lbma_filters_by_start() -> None:
    responses = [_listing_response(), _xlsx_response()]
    with patch.object(LbmaProvider, "_get_with_telemetry", side_effect=responses):
        with LbmaProvider() as p:
            rows = p.fetch_monthly(start=date(2026, 4, 1))
    assert [r.obs_date for r in rows] == [date(2026, 4, 1)]


def test_lbma_no_xlsx_url_returns_empty() -> None:
    empty_listing = httpx.Response(
        200,
        text="<html><body>no links</body></html>",
        request=httpx.Request("GET", LbmaProvider.LISTING_URL),
    )
    with patch.object(LbmaProvider, "_get_with_telemetry", return_value=empty_listing):
        with LbmaProvider() as p:
            rows = p.fetch_monthly()
    assert rows == []
