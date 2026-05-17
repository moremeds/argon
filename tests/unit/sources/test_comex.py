"""COMEX vault scraper."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.comex import ComexProvider, ComexVaultRow

SAMPLE_HTML = """
<table id="metal-stocks-gold">
  <tr><th>Date</th><th>Registered (oz)</th><th>Eligible (oz)</th><th>Total (oz)</th></tr>
  <tr><td>05/15/2026</td><td>17,500,100</td><td>10,820,200</td><td>28,320,300</td></tr>
  <tr><td>05/14/2026</td><td>17,320,000</td><td>10,810,000</td><td>28,130,000</td></tr>
</table>
"""


def _fake_response() -> httpx.Response:
    return httpx.Response(
        200,
        text=SAMPLE_HTML,
        request=httpx.Request("GET", ComexProvider.URL),
    )


def test_comex_parses_vault_table():
    with patch.object(ComexProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with ComexProvider() as p:
            rows = p.fetch_vault(start=date(2026, 5, 14))
    assert len(rows) == 2
    assert rows[0] == ComexVaultRow(
        obs_date=date(2026, 5, 15),
        registered_oz=Decimal("17500100"),
        eligible_oz=Decimal("10820200"),
        total_oz=Decimal("28320300"),
    )


def test_comex_returns_empty_when_table_missing():
    with patch.object(ComexProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = httpx.Response(
            200,
            text="<html><body>no table here</body></html>",
            request=httpx.Request("GET", ComexProvider.URL),
        )
        with ComexProvider() as p:
            rows = p.fetch_vault()
    assert rows == []
