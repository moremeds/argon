from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.cftc_tff import CftcTffProvider


SAMPLE = """[
  {
    "market_and_exchange_names": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
    "contract_market_name": "UST 10Y NOTE",
    "cftc_contract_market_code": "043602",
    "commodity_name": "T-NOTES, 6.5-10 YEAR",
    "commodity_subgroup_name": "Interest Rates - U.S. Treasury",
    "report_date_as_yyyy_mm_dd": "2026-05-19T00:00:00.000",
    "open_interest_all": "4544233",
    "dealer_positions_long_all": "416965",
    "dealer_positions_short_all": "514194",
    "asset_mgr_positions_long": "2155592",
    "asset_mgr_positions_short": "854840",
    "lev_money_positions_long": "625134",
    "lev_money_positions_short": "1819579",
    "other_rept_positions_long": "189323",
    "other_rept_positions_short": "319340",
    "futonly_or_combined": "FutOnly"
  },
  {
    "contract_market_name": "GOLD",
    "cftc_contract_market_code": "088691",
    "commodity_subgroup_name": "Metals and Other Physical",
    "report_date_as_yyyy_mm_dd": "2026-05-19T00:00:00.000"
  }
]"""


def test_cftc_tff_provider_parses_treasury_futures_rows() -> None:
    response = httpx.Response(
        200,
        text=SAMPLE,
        request=httpx.Request("GET", CftcTffProvider.URL),
    )

    with patch.object(CftcTffProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = response
        with CftcTffProvider() as provider:
            rows = provider.fetch_treasury_rows(start=date(2026, 1, 1))

    assert len(rows) == 1
    row = rows[0]
    assert row.contract_code == "043602"
    assert row.tenor_bucket == "10Y"
    assert row.obs_date == date(2026, 5, 19)
    assert row.release_date == date(2026, 5, 22)
    assert row.open_interest == Decimal("4544233")
    assert row.dealer_net == Decimal("-97229")
    assert row.asset_mgr_net == Decimal("1300752")
    assert row.lev_money_net == Decimal("-1194445")
    assert row.lev_money_net_pct_oi == Decimal("-26.3")

    _, params = mock_get.call_args.args
    assert 'commodity_subgroup_name="Interest Rates - U.S. Treasury"' in params["$where"]
    assert 'report_date_as_yyyy_mm_dd >= "2026-01-01T00:00:00"' in params["$where"]
