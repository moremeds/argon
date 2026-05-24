from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.treasury_supply import TreasurySupplyProvider


AUCTION_SAMPLE = """[
  {
    "cusip": "912810UL0",
    "securityType": "Bond",
    "securityTerm": "30-Year",
    "auctionDate": "2026-05-14T00:00:00",
    "issueDate": "2026-05-15T00:00:00",
    "offeringAmount": "25000000000",
    "highYield": "5.046000",
    "bidToCoverRatio": "2.300000",
    "directBidderAccepted": "5069000000",
    "indirectBidderAccepted": "14125000000",
    "primaryDealerAccepted": "5806000000",
    "totalAccepted": "25000000000",
    "pdfFilenameCompetitiveResults": "R_20260514_1.pdf"
  },
  {
    "cusip": "91282CPU9",
    "securityType": "Note",
    "securityTerm": "9-Year 8-Month",
    "auctionDate": "2026-05-21T00:00:00",
    "issueDate": "2026-05-29T00:00:00",
    "offeringAmount": "16000000000",
    "highYield": "5.122000",
    "bidToCoverRatio": "2.550000",
    "directBidderAccepted": "3168000000",
    "indirectBidderAccepted": "9328000000",
    "primaryDealerAccepted": "1296000000",
    "totalAccepted": "16000000000",
    "pdfFilenameCompetitiveResults": "R_20260521_1.pdf"
  },
  {
    "cusip": "912797NW3",
    "securityType": "Bill",
    "securityTerm": "13-Week",
    "auctionDate": "2026-05-18T00:00:00",
    "issueDate": "2026-05-21T00:00:00",
    "offeringAmount": "89000000000",
    "highDiscountRate": "3.600000",
    "bidToCoverRatio": "2.860000",
    "directBidderAccepted": "10000000000",
    "indirectBidderAccepted": "50000000000",
    "primaryDealerAccepted": "29000000000",
    "totalAccepted": "89000000000",
    "pdfFilenameCompetitiveResults": "R_20260518_1.pdf"
  }
]"""

DEBT_SAMPLE = """{
  "data": [
    {
      "record_date": "2026-05-21",
      "debt_held_public_amt": "31374788661132.13",
      "intragov_hold_amt": "7696411796234.32",
      "tot_pub_debt_out_amt": "39071200457366.45"
    }
  ]
}"""


def test_treasury_supply_provider_parses_auction_rows_and_debt() -> None:
    auction_response = httpx.Response(
        200,
        text=AUCTION_SAMPLE,
        request=httpx.Request("GET", TreasurySupplyProvider.AUCTIONS_URL),
    )
    debt_response = httpx.Response(
        200,
        text=DEBT_SAMPLE,
        request=httpx.Request("GET", TreasurySupplyProvider.DEBT_TO_PENNY_URL),
    )

    with patch.object(TreasurySupplyProvider, "_get_with_telemetry") as mock_get:
        mock_get.side_effect = [auction_response, debt_response]
        with TreasurySupplyProvider() as provider:
            auctions = provider.fetch_recent_auctions(start=date(2026, 5, 1))
            debt = provider.fetch_latest_debt()

    assert [row.security_term for row in auctions] == [
        "30-Year",
        "9-Year 8-Month",
        "13-Week",
    ]
    assert auctions[0].tail_indicator == "long-end"
    assert auctions[0].high_rate == Decimal("5.046000")
    assert auctions[0].offering_amount == Decimal("25000000000")
    assert auctions[0].bid_to_cover == Decimal("2.300000")
    assert auctions[1].tail_indicator == "belly"
    assert auctions[2].high_rate == Decimal("3.600000")
    assert debt.record_date == date(2026, 5, 21)
    assert debt.debt_held_public == Decimal("31374788661132.13")

    auction_params = mock_get.call_args_list[0].args[1]
    assert auction_params["format"] == "json"
    assert "type" not in auction_params
