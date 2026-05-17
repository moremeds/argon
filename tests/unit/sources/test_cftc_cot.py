"""CFTC COT disaggregated weekly parser."""

from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.cftc_cot import CftcCotProvider

SAMPLE = """Report_Date_as_YYYY-MM-DD,Report_Date_as_YYYY-MM-DD_Release,Open_Interest_All,M_Money_Positions_Long_All,M_Money_Positions_Short_All,Prod_Merc_Positions_Long_ALL,Prod_Merc_Positions_Short_ALL
2026-05-13,2026-05-16,512000,210500,85300,180100,295400
2026-05-06,2026-05-09,508100,205200,90100,175300,293000
"""


def _fake_response() -> httpx.Response:
    return httpx.Response(
        200,
        text=SAMPLE,
        request=httpx.Request("GET", CftcCotProvider.URL),
    )


def test_cot_parses_disaggregated_csv():
    with patch.object(CftcCotProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with CftcCotProvider() as p:
            rows = p.fetch_weekly(start=date(2026, 5, 6))
    assert len(rows) == 2
    assert rows[0].obs_date == date(2026, 5, 13)
    assert rows[0].release_date == date(2026, 5, 16)
    assert rows[0].mm_long == Decimal("210500")
    assert rows[0].mm_net == Decimal("125200")
    assert rows[0].comm_net == Decimal("-115300")
