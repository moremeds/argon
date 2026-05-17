"""LBMA monthly vault parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.lbma import LbmaProvider, LbmaVaultRow

SAMPLE = """Date,Gold (tonnes),Gold (oz),Silver (tonnes),Silver (oz)
2026-04-30,8523.4,274086000,33500.2,1077000000
2026-03-31,8541.1,274655000,33620.4,1080900000
"""


def _fake_response() -> httpx.Response:
    return httpx.Response(
        200,
        text=SAMPLE,
        request=httpx.Request("GET", LbmaProvider.URL),
    )


def test_lbma_parses_monthly_csv():
    with patch.object(LbmaProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with LbmaProvider() as p:
            rows = p.fetch_monthly(start=date(2026, 3, 31))
    assert len(rows) == 2
    assert rows[0] == LbmaVaultRow(
        obs_date=date(2026, 4, 30),
        vault_oz=Decimal("274086000"),
    )
