from __future__ import annotations

from datetime import date
from decimal import Decimal
from unittest.mock import patch

import httpx

from uw_scan.sources.treasury_supply import TreasurySupplyProvider


# Real TreasuryDirect ``TA_WS/securities/auctioned`` rows, frozen 2026-08-21.  The last
# two are the taxonomy collision spec 2.1 names: both are securityTerm "10-Year",
# securityType "Note", and one is a nominal note at $42bn while the other is a TIPS at
# $21bn.  Only the ``type`` field separates them, which is why the supply series key is
# (securityTerm, type) and not the term alone.
AUCTION_SAMPLE = """[
  {
    "cusip": "912810UW6",
    "securityType": "Bond",
    "securityTerm": "30-Year",
    "type": "Bond",
    "reopening": "No",
    "announcementDate": "2026-08-05T00:00:00",
    "auctionDate": "2026-08-13T00:00:00",
    "issueDate": "2026-08-17T00:00:00",
    "offeringAmount": "25000000000",
    "highYield": "5.2160",
    "bidToCoverRatio": "2.390000",
    "directBidderAccepted": "5390150000",
    "indirectBidderAccepted": "16647723000",
    "primaryDealerAccepted": "2866735000",
    "totalAccepted": "31323533800",
    "pdfFilenameCompetitiveResults": "R_20260813_3.pdf"
  },
  {
    "cusip": "912797UZ8",
    "securityType": "Bill",
    "securityTerm": "13-Week",
    "type": "Bill",
    "reopening": "Yes",
    "announcementDate": "2026-08-13T00:00:00",
    "auctionDate": "2026-08-17T00:00:00",
    "issueDate": "2026-08-20T00:00:00",
    "offeringAmount": "92000000000",
    "highDiscountRate": "3.715000",
    "bidToCoverRatio": "2.860000",
    "directBidderAccepted": "6074000000",
    "indirectBidderAccepted": "48135888100",
    "primaryDealerAccepted": "35216880000",
    "totalAccepted": "98725863900",
    "pdfFilenameCompetitiveResults": "R_20260817_1.pdf"
  },
  {
    "cusip": "91282CRF0",
    "securityType": "Note",
    "securityTerm": "10-Year",
    "type": "Note",
    "reopening": "No",
    "announcementDate": "2026-08-05T00:00:00",
    "auctionDate": "2026-08-12T00:00:00",
    "issueDate": "2026-08-17T00:00:00",
    "offeringAmount": "42000000000",
    "highYield": "4.6830",
    "bidToCoverRatio": "2.530000",
    "directBidderAccepted": "6135867600",
    "indirectBidderAccepted": "32087936000",
    "primaryDealerAccepted": "3597810000",
    "totalAccepted": "52623557100",
    "pdfFilenameCompetitiveResults": "R_20260812_2.pdf"
  },
  {
    "cusip": "91282CRE3",
    "securityType": "Note",
    "securityTerm": "10-Year",
    "type": "TIPS",
    "reopening": "No",
    "announcementDate": "2026-07-16T00:00:00",
    "auctionDate": "2026-07-23T00:00:00",
    "issueDate": "2026-07-31T00:00:00",
    "offeringAmount": "21000000000",
    "highYield": "2.4380",
    "bidToCoverRatio": "2.300000",
    "totalAccepted": "23321784700",
    "pdfFilenameCompetitiveResults": "R_20260723_3.pdf"
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

    assert [row.cusip for row in auctions] == [
        "912810UW6",
        "912797UZ8",
        "91282CRF0",
        "91282CRE3",
    ]
    assert auctions[0].tail_indicator == "long-end"
    assert auctions[0].high_rate == Decimal("5.2160")
    assert auctions[0].offering_amount == Decimal("25000000000")
    assert auctions[0].bid_to_cover == Decimal("2.390000")
    assert auctions[0].announcement_date == date(2026, 8, 5)
    assert auctions[0].reopening is False
    assert auctions[1].tail_indicator == "bill"
    assert auctions[1].high_rate == Decimal("3.715000")
    assert auctions[1].reopening is True
    assert auctions[2].tail_indicator == "belly"

    # The term and the securityType are identical; only ``type`` and the size differ.
    nominal, tips = auctions[2], auctions[3]
    assert (nominal.security_term, nominal.security_type) == (
        tips.security_term,
        tips.security_type,
    )
    assert (nominal.instrument_type, tips.instrument_type) == ("Note", "TIPS")
    assert nominal.offering_amount == tips.offering_amount * 2
    assert debt.record_date == date(2026, 5, 21)
    assert debt.debt_held_public == Decimal("31374788661132.13")

    auction_params = mock_get.call_args_list[0].args[1]
    assert auction_params["format"] == "json"
    assert "type" not in auction_params


def test_the_type_parameter_reaches_the_request() -> None:
    """The 250-row cap applies per request, so ``type`` is what selects the window.

    Unfiltered, the cap is spent across every security type and reaches back eighteen
    months -- six new issues per coupon term, one above the five the supply baseline
    needs. ``type=Note`` reaches 2021 and ``type=Bond`` reaches 2012. Dropping the
    parameter does not fail; it silently returns a shallower history.
    """
    response = httpx.Response(
        200,
        text=AUCTION_SAMPLE,
        request=httpx.Request("GET", TreasurySupplyProvider.AUCTIONS_URL),
    )
    with patch.object(TreasurySupplyProvider, "_get_with_telemetry") as mock_get:
        mock_get.return_value = response
        with TreasurySupplyProvider() as provider:
            provider.fetch_auctions_payload(security_type="Bond")

    _, params = mock_get.call_args.args
    assert params["type"] == "Bond"
