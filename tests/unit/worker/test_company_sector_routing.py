"""Vendor-sector routing: the second pass that answers "is this a bank?".

Two things are pinned here, and the second is the one that will bite:

- a real vendor payload parses to a sector, and an absent one to None;
- the two sector vocabularies stay in separate maps, because they collide.
"""

from __future__ import annotations

from uw_scan.fundamentals.valuation import (
    EV_DENOMINATED,
    FINANCIALS,
    TYPE_YIELD,
    UNCLASSIFIED,
)
from uw_scan.worker.jobs.company_sector_refresh import parse_sector
from uw_scan.worker.jobs.fundamental_anchors import (
    TICKER_TO_TYPE,
    SECTOR_TO_TYPE,
    VENDOR_SECTOR_TO_TYPE,
)

# UW's real `/api/stock/AXP/info` response, captured 2026-08-19. Trimmed to the
# fields the parser reads plus enough neighbours to keep the shape honest.
AXP_INFO = {
    "data": {
        "full_name": "AMERICAN EXPRESS",
        "issue_type": "Common Stock",
        "marketcap": "228605884667",
        "sector": "Financial Services",
        "symbol": "AXP",
    },
    "price": "343.6125",
}


def test_a_real_vendor_payload_yields_its_sector():
    assert parse_sector(AXP_INFO) == "Financial Services"


def test_a_missing_or_blank_sector_is_None_not_an_empty_string():
    """One shape for "the vendor cannot classify this name".

    A stored `""` would be a distinct key that matches no rule, so it would
    behave like None while looking like data — and `tickers_needing_fetch`
    would treat it as answered, which it is, making the difference invisible
    exactly where it matters.
    """
    assert parse_sector({"data": {"symbol": "AAA"}}) is None
    assert parse_sector({"data": {"symbol": "AAA", "sector": "   "}}) is None
    assert parse_sector({"data": None}) is None
    assert parse_sector({}) is None
    assert parse_sector(None) is None


def test_the_two_vocabularies_disagree_about_Energy_and_are_kept_apart():
    """THE regression test for this change.

    `Energy` exists in both vocabularies and means different things: argon's
    chain taxonomy means power generation by it and routes it to `power_infra`
    (EV/EBITDA), while the vendor's GICS-style vocabulary means oil and gas.
    Merging the maps — or feeding a vendor sector through the chain map — would
    silently reprice every energy name with no error anywhere.
    """
    assert SECTOR_TO_TYPE["Energy"] == "power_infra"
    assert "Energy" not in VENDOR_SECTOR_TO_TYPE


def test_the_vendor_map_answers_one_question_and_does_not_reclassify_the_universe():
    """It exists for the routing question the chain taxonomy cannot answer.

    Every other vendor sector must keep falling through to UNCLASSIFIED exactly
    as before, or this change quietly becomes a re-rating of the whole panel
    under the name of a bank fix.
    """
    assert VENDOR_SECTOR_TO_TYPE == {"Financial Services": FINANCIALS}
    for sector in ("Technology", "Healthcare", "Utilities", "Industrials"):
        assert VENDOR_SECTOR_TO_TYPE.get(sector, UNCLASSIFIED) == UNCLASSIFIED


def test_the_chain_taxonomy_routes_its_own_financial_labels():
    """`Banks` and `Fintech` reach the refusal without needing a vendor call —
    they are the 8 of 11 panel financials that carry a watchlist row."""
    assert SECTOR_TO_TYPE["Banks"] == FINANCIALS
    assert SECTOR_TO_TYPE["Fintech"] == FINANCIALS


def test_prefix_matching_cannot_drag_a_neighbour_into_the_refusal():
    """Chain sectors match by PREFIX, so a new label starting with `Bank...`
    would inherit the refusal silently. No such label exists today; this fails
    if one is added without a decision."""
    financial_prefixes = {k for k, v in SECTOR_TO_TYPE.items() if v == FINANCIALS}
    assert financial_prefixes == {"Banks", "Fintech"}


def test_every_name_override_escapes_via_a_market_cap_method_not_an_exemption():
    """The load-bearing invariant of `TICKER_TO_TYPE`, and the one that will rot.

    A name is only allowed out of the financials refusal because the type it
    lands in is priced by MARKET CAP, so the enterprise-value denominator the
    refusal exists to reject is never computed for it. Route an override to an
    EV-denominated type and that argument silently evaporates while the entry
    still looks deliberate — which is the exact failure this whole change
    replaces, re-created one ticker at a time.
    """
    assert TICKER_TO_TYPE, "the map is documented as holding a real entry"
    for ticker, ctype in TICKER_TO_TYPE.items():
        method = TYPE_YIELD.get(ctype)
        assert method is not None, f"{ticker} overridden to a type with no yield"
        assert method not in EV_DENOMINATED, (
            f"{ticker} -> {ctype} is priced through enterprise value; the "
            "override's justification does not hold for it"
        )


def test_PYPL_is_the_override_and_it_beats_both_sector_passes():
    """Named explicitly, because a silent one is a routing bug in disguise.

    PYPL carries chain sector `Fintech` AND vendor sector `Financial Services`,
    so BOTH passes would refuse it. The override is the only thing standing
    between it and a lost band, and it is checked first for that reason.
    """
    assert TICKER_TO_TYPE == {"PYPL": "platform_scale"}
    assert SECTOR_TO_TYPE["Fintech"] == FINANCIALS
    assert VENDOR_SECTOR_TO_TYPE["Financial Services"] == FINANCIALS


def test_parse_sector_against_the_real_captured_vendor_payload():
    """The envelope, settled by the vendor rather than by the spec.

    `docs/uw-samples/unusual_whales_api_spec.yaml` declares `Ticker Info` FLAT —
    `sector` as a top-level property, no `data` wrapper. It is wrong. This
    asserts against the response actually captured from `/api/stock/JPM/info`
    on 2026-08-20, because a stub written to match the parser proves only that
    the parser matches the stub. Trusting the spec here would make this return
    None for every ticker, which the job stores as "the vendor has no sector"
    and never re-asks: silent, permanent, and 450 names wide.

    JPM is the right fixture twice over — its real sector is the one string
    `VENDOR_SECTOR_TO_TYPE` maps, so this pins the whole vendor path.
    """
    import json
    from pathlib import Path

    sample = Path(__file__).resolve().parents[3] / "docs/uw-samples/stock_info.json"
    body = json.loads(sample.read_text())["response"]
    assert parse_sector(body) == "Financial Services"
    assert VENDOR_SECTOR_TO_TYPE[parse_sector(body)] == FINANCIALS
