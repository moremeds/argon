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

CURRENT_DISAGG_SAMPLE = """"SILVER - COMMODITY EXCHANGE INC.",260512,2026-05-12,084691,CMX ,01,084 ,103800,1437,21069,20697,44711,5207,21191,5430,8619
"GOLD - COMMODITY EXCHANGE INC.",260512,2026-05-12,088691,CMX ,01,088 ,376496,11437,31639,25671,215727,20617,127242,29227,36664
"MICRO GOLD - COMMODITY EXCHANGE INC.",260512,2026-05-12,088695,CMX ,01,088 ,67067,232,0,5865,0,0,531,0,1
"""

HISTORY_SAMPLE = """[
  {
    "report_date_as_yyyy_mm_dd": "2026-05-12T00:00:00.000",
    "cftc_contract_market_code": "088691",
    "open_interest_all": "376496",
    "prod_merc_positions_long": "11437",
    "prod_merc_positions_short": "31639",
    "m_money_positions_long_all": "127242",
    "m_money_positions_short_all": "29227"
  },
  {
    "report_date_as_yyyy_mm_dd": "2026-05-05T00:00:00.000",
    "cftc_contract_market_code": "084691",
    "open_interest_all": "103800",
    "prod_merc_positions_long": "1437",
    "prod_merc_positions_short": "21069",
    "m_money_positions_long_all": "21191",
    "m_money_positions_short_all": "5430"
  }
]"""


def _fake_response(text: str = SAMPLE) -> httpx.Response:
    return httpx.Response(
        200,
        text=text,
        request=httpx.Request("GET", CftcCotProvider.URL),
    )


def test_cot_parses_disaggregated_csv():
    with patch.object(CftcCotProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response()
        with CftcCotProvider() as p:
            rows = p.fetch_weekly()
    assert len(rows) == 2
    assert rows[0].obs_date == date(2026, 5, 13)
    assert rows[0].release_date == date(2026, 5, 16)
    assert rows[0].mm_long == Decimal("210500")
    assert rows[0].mm_net == Decimal("125200")
    assert rows[0].comm_net == Decimal("-115300")


def test_cot_parses_current_disaggregated_file_and_filters_gold_contract():
    with patch.object(CftcCotProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response(CURRENT_DISAGG_SAMPLE)
        with CftcCotProvider() as p:
            rows = p.fetch_weekly()

    assert len(rows) == 1
    assert rows[0].obs_date == date(2026, 5, 12)
    assert rows[0].release_date == date(2026, 5, 15)
    assert rows[0].open_interest == Decimal("376496")
    assert rows[0].mm_long == Decimal("127242")
    assert rows[0].mm_short == Decimal("29227")
    assert rows[0].mm_net == Decimal("98015")
    assert rows[0].comm_long == Decimal("11437")
    assert rows[0].comm_short == Decimal("31639")
    assert rows[0].comm_net == Decimal("-20202")


def test_cot_fetches_history_from_public_reporting_api_when_start_is_supplied():
    with patch.object(CftcCotProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = _fake_response(HISTORY_SAMPLE)
        with CftcCotProvider() as p:
            rows = p.fetch_weekly(start=date(2025, 4, 13))

    mock_get.assert_called_once()
    url, params = mock_get.call_args.args
    assert url == CftcCotProvider.HISTORY_URL
    assert params["$where"] == (
        'cftc_contract_market_code="088691" AND '
        'report_date_as_yyyy_mm_dd >= "2025-04-13T00:00:00"'
    )
    assert params["$order"] == "report_date_as_yyyy_mm_dd ASC"
    assert rows[0].obs_date == date(2026, 5, 12)
    assert rows[0].release_date == date(2026, 5, 15)
    assert rows[0].mm_net == Decimal("98015")
    assert rows[0].comm_net == Decimal("-20202")
