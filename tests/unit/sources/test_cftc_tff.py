from __future__ import annotations

import json

from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from unittest.mock import patch

import httpx
import pytest

from uw_scan.normalize import NormalizationError
from uw_scan.sources.cftc_tff import CftcTffProvider, parse_treasury_rows


# Real CFTC TFF futures-only rows, frozen at authoring time (fetched 2026-08-21).  The
# ``:created_at`` values are the publisher's own load instants: report 2026-05-19 landed
# on the Friday the +3d rule predicted, and report 2026-06-16 landed the following Monday
# because Juneteenth moved the release.  Both are needed -- one week where the rule
# happened to be right proves nothing about the week where it was not.
SAMPLE = """[
  {
    "market_and_exchange_names": "UST 10Y NOTE - CHICAGO BOARD OF TRADE",
    ":created_at": "2026-05-22T19:30:55.580Z",
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
    ":created_at": "2026-05-22T19:30:55.580Z",
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
    assert row.release_at == datetime(2026, 5, 22, 19, 30, 55, 580000, tzinfo=UTC)
    assert row.release_date == date(2026, 5, 22)
    assert row.open_interest == Decimal("4544233")
    assert row.dealer_net == Decimal("-97229")
    assert row.asset_mgr_net == Decimal("1300752")
    assert row.lev_money_net == Decimal("-1194445")
    assert row.lev_money_net_pct_oi == Decimal("-26.3")

    _, params = mock_get.call_args.args
    assert params["$select"].startswith(":created_at,")
    assert "lev_money_positions_short" in params["$select"]
    assert (
        'commodity_subgroup_name="Interest Rates - U.S. Treasury"' in params["$where"]
    )
    assert 'report_date_as_yyyy_mm_dd >= "2026-01-01T00:00:00"' in params["$where"]


#: The real CFTC TFF row for report 2026-06-16, contract 043602, fetched 2026-08-22.
#: Complete, because the trimmed version this replaces carried only the leveraged-money
#: legs -- and carried them WRONG (610000/2692236 against the published 298774/2381010).
#: A positioning fixture missing three counterparty categories cannot exercise the
#: distribution rules it is meant to protect, and one with invented legs asserts against
#: a report that was never published.
HOLIDAY_SHIFTED = """[
  {
    "report_date_as_yyyy_mm_dd": "2026-06-16T00:00:00.000",
    ":created_at": "2026-06-22T19:30:53.455Z",
    "cftc_contract_market_code": "043602",
    "contract_market_name": "UST 10Y NOTE",
    "commodity_name": "T-NOTES, 6.5-10 YEAR",
    "open_interest_all": "5324590",
    "dealer_positions_long_all": "170280",
    "dealer_positions_short_all": "610039",
    "asset_mgr_positions_long": "3345129",
    "asset_mgr_positions_short": "860128",
    "lev_money_positions_long": "298774",
    "lev_money_positions_short": "2381010",
    "other_rept_positions_long": "225526",
    "other_rept_positions_short": "208283"
  }
]"""


def test_release_date_comes_from_the_publisher_not_from_a_schedule_rule() -> None:
    """The Juneteenth week, which the retired ``obs_date + 3 days`` rule got wrong.

    CFTC loaded report 2026-06-16 on Monday 2026-06-22.  The rule said Friday
    2026-06-19, so a replay anywhere in that gap read a position that had not been
    published -- lookahead, and it shipped in this table for as long as the rule did.
    """
    response = httpx.Response(
        200,
        text=HOLIDAY_SHIFTED,
        request=httpx.Request("GET", CftcTffProvider.URL),
    )
    with patch.object(CftcTffProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = response
        with CftcTffProvider() as provider:
            rows = provider.fetch_treasury_rows()

    assert rows[0].release_date == date(2026, 6, 22)
    assert rows[0].release_date != rows[0].obs_date + timedelta(days=3)


def test_payload_without_the_system_field_fails_loudly() -> None:
    """A silent $select regression must not read as "CFTC published nothing"."""
    response = httpx.Response(
        200,
        text=HOLIDAY_SHIFTED.replace('":created_at": "2026-06-22T19:30:53.455Z",', ""),
        request=httpx.Request("GET", CftcTffProvider.URL),
    )
    with patch.object(CftcTffProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = response
        with CftcTffProvider() as provider:
            with pytest.raises(NormalizationError, match=":created_at"):
                provider.fetch_treasury_rows()


class TestAPartialDistributionIsNotADegradedOne:
    """A dropped row does not make positioning noisier -- it makes a different answer.

    Positioning is a distribution across counterparty categories: a leveraged short is
    somebody else's long. Losing one category silently and reporting the rest reads as
    complete. The parser previously logged such a row at debug level and returned the
    survivors.
    """

    @staticmethod
    def _payload(rows: list[dict]) -> bytes:
        return json.dumps(rows).encode()

    @staticmethod
    def _row(**overrides) -> dict:
        # A real 10-year note future row, frozen from the CFTC TFF payload.
        row = {
            ":created_at": "2026-08-14T19:30:07.014Z",
            "cftc_contract_market_code": "043602",
            "contract_market_name": "10 YEAR NOTE",
            "commodity_name": "TREASURY",
            "report_date_as_yyyy_mm_dd": "2026-08-11T00:00:00.000",
            "open_interest_all": "6120537",
            "dealer_positions_long_all": "254048",
            "dealer_positions_short_all": "1607063",
            "asset_mgr_positions_long": "3134595",
            "asset_mgr_positions_short": "471398",
            "lev_money_positions_long": "1130275",
            "lev_money_positions_short": "3049691",
            "other_rept_positions_long": "530584",
            "other_rept_positions_short": "175128",
        }
        row.update(overrides)
        return row

    def test_a_healthy_payload_parses(self) -> None:
        rows = parse_treasury_rows(self._payload([self._row()]))
        assert len(rows) == 1
        assert rows[0].contract_code == "043602"

    def test_a_tracked_contract_that_will_not_parse_fails_the_release(self) -> None:
        broken = self._row()
        del broken["lev_money_positions_short"]
        with pytest.raises(NormalizationError, match="043602"):
            parse_treasury_rows(self._payload([self._row(), broken]))

    def test_the_failure_says_a_partial_distribution_is_a_different_reading(
        self,
    ) -> None:
        broken = self._row(open_interest_all="not-a-number")
        with pytest.raises(NormalizationError, match="different reading"):
            parse_treasury_rows(self._payload([broken]))

    def test_an_untracked_contract_is_skipped_without_failing(self) -> None:
        """Not every row in the payload is ours; a corn future is not our problem."""
        corn = {"cftc_contract_market_code": "002602", ":created_at": "x"}
        rows = parse_treasury_rows(self._payload([self._row(), corn]))
        assert len(rows) == 1
