"""`GET /api/scanner/value` — every name inside its OWN valuation buy zone.

The wiring under test is the one thing this endpoint exists to get right: it
lists names side by side WITHOUT ranking them. Own-history value measured
(`sales_to_ev` within-ticker 2q IC +0.0744, t 5.77); cross-sectional value
measured INVERTED in the same universe (`book_to_price` IC -0.0365, t -2.32).
An ordering by `spot_percentile` would therefore ship the refuted claim under
the validated one's name, and nothing about the response shape would show it.

Every figure below is a real row from the mini's `valuation_anchors` at
engine `fundamentals-v1:77aea364`, as_of 2026-08-14 and 2026-08-17, frozen.
"""

from __future__ import annotations

from datetime import date

import psycopg
import pytest

from uw_scan.fundamentals.features import FEATURES
from uw_scan.storage.fundamental_anchors import FundamentalAnchorsRepository
from uw_scan.storage.fundamental_scores import FundamentalScoresRepository

ENGINE = "test-v1:bbbbbbbb"
D14, D17 = date(2026, 8, 14), date(2026, 8, 17)

_UNCLASSIFIED_REASON = (
    "no sector on file for this name, so the band uses the pooled-universe "
    "default (revenue / enterprise value) rather than a method chosen for its "
    "business"
)

# ticker, as_of, company_type, method, band(5), spot, pct, confidence, reasons.
#
# BAX and CL cross INTO their zones between the two dates; BRO is already in on
# both; AAON has no 08-14 row at all; AAPL never enters; NVDA's band is REFUSED
# (every level null) because its own 20q range spans 16.9x.
# The frozen table is a fixture, not code: one row per line stays readable.
# fmt: off
ROWS = [
    # entrant — the percentile is IDENTICAL on both dates while membership
    # flips. Percentile is quantised to 1/history_quarters (0.05 here), so it
    # cannot resolve a 3% move in spot; zone membership can. This one pair is
    # why the list keys on the band and not on the percentile.
    ("BAX",  D14, "unclassified",   "sales_to_ev", (26.5389800492436, 35.4204243981301, 39.6686490583759, 43.5196914218796, 51.9278503121108),  26.73, 0.80, "medium", [_UNCLASSIFIED_REASON]),
    ("BAX",  D17, "unclassified",   "sales_to_ev", (26.5389800492436, 35.4204243981301, 39.6686490583759, 43.5196914218796, 51.9278503121108),  25.91, 0.80, "medium", [_UNCLASSIFIED_REASON]),
    # entrant
    ("CL",   D14, "unclassified",   "sales_to_ev", (91.1992225192692, 94.0368641096543, 96.7091413724127, 99.4883467005916, 101.543794965356),  91.95, 0.70, "medium", [_UNCLASSIFIED_REASON]),
    ("CL",   D17, "unclassified",   "sales_to_ev", (91.1992225192692, 94.0368641096543, 96.7091413724127, 99.4883467005916, 101.543794965356),  90.21, 0.85, "medium", [_UNCLASSIFIED_REASON]),
    # incumbent, and the HIGHEST percentile in the set — it must sort LAST.
    ("BRO",  D14, "unclassified",   "sales_to_ev", (89.0239946849381, 94.6689713635838, 98.2146289248685, 108.081847937418, 110.555108451492),  70.54, 0.95, "medium", [_UNCLASSIFIED_REASON]),
    ("BRO",  D17, "unclassified",   "sales_to_ev", (89.0239946849381, 94.6689713635838, 98.2146289248685, 108.081847937418, 110.555108451492),  68.86, 1.00, "medium", [_UNCLASSIFIED_REASON]),
    # first band on 08-17 — in zone, but with nothing to compare against.
    ("AAON", D17, "unclassified",   "sales_to_ev", (121.070172484609, 139.899206395853, 146.392572443225, 159.327451571987, 173.026409635574),  88.09, 1.00, "medium", [_UNCLASSIFIED_REASON]),
    # never in zone: spot 305.59 against a 247.15 buy_below.
    ("AAPL", D14, "platform_scale", "fcf_yield",   (247.148852825911, 256.271251067733, 263.21538506886, 299.498524430179, 308.282594446711), 305.93, 0.25, "high",   []),
    ("AAPL", D17, "platform_scale", "fcf_yield",   (247.148852825911, 256.271251067733, 263.21538506886, 299.498524430179, 308.282594446711), 305.59, 0.25, "high",   []),
    # REFUSED band: priced by no level, so it can be in no zone.
    ("NVDA", D17, "platform_scale", "fcf_yield",   (None, None, None, None, None),                                                            225.01, None, "none",   ["own 20-quarter valuation range spans 16.9x, wider than the 4x limit"]),
]
# fmt: on


def _seed(seeded) -> None:
    scores = FundamentalScoresRepository(seeded.conn, schema=seeded._schema)
    scores.register_version(
        engine_version=ENGINE,
        code_version="test-v1",
        param_hash="bbbbbbbb",
        params=dict.fromkeys(FEATURES, 1.0),
        note="test",
    )
    scores.activate(ENGINE)
    FundamentalAnchorsRepository(seeded.conn, schema=seeded._schema).insert_anchors(
        [
            {
                "ticker": t,
                "as_of": d,
                "engine_version": ENGINE,
                "inputs_hash": f"{t}-{d}",
                "company_type": ctype,
                "method": method,
                "buy_below": band[0],
                "observe_low": band[1],
                "observe_mid": band[2],
                "observe_high": band[3],
                "risk_above": band[4],
                "spot": spot,
                "spot_percentile": pct,
                "history_quarters": 20,
                "confidence": conf,
                "confidence_reasons_jsonb": reasons,
                "inputs_jsonb": {},
                "source_obs_ids": [],
            }
            for t, d, ctype, method, band, spot, pct, conf, reasons in ROWS
        ]
    )


def test_only_names_at_or_below_their_own_buy_below_are_listed(
    client, seeded_db_empty_cards
):
    _seed(seeded_db_empty_cards)
    body = client.get("/api/scanner/value").json()
    assert {c["ticker"] for c in body["candidates"]} == {"AAON", "BAX", "BRO", "CL"}
    assert body["as_of"] == "2026-08-17"


def test_a_refused_band_is_in_neither_the_list_nor_the_denominator(
    client, seeded_db_empty_cards
):
    """NVDA has a row on 08-17 with every level null. Counting it as covered
    would inflate the denominator with a name the method declined to price."""
    _seed(seeded_db_empty_cards)
    body = client.get("/api/scanner/value").json()
    assert "NVDA" not in {c["ticker"] for c in body["candidates"]}
    # AAON, AAPL, BAX, BRO, CL carry a buy_below on 08-17. NVDA does not.
    assert body["banded_universe"] == 5


def test_the_list_is_not_ordered_by_cheapness(client, seeded_db_empty_cards):
    """The anti-regression test for the whole design.

    BRO sits at percentile 1.00 — cheaper against its own past than any other
    row here — and must come LAST, because it is not news. A `sort` parameter
    over `spot_percentile` would flip this, and it must never be added.
    """
    _seed(seeded_db_empty_cards)
    got = [c["ticker"] for c in client.get("/api/scanner/value").json()["candidates"]]
    # Newly-entered first, then alphabetical within each group.
    assert got == ["BAX", "CL", "AAON", "BRO"]
    by_cheapness = ["BRO", "AAON", "CL", "BAX"]  # percentile 1.00, 1.00, .85, .80
    assert got != by_cheapness


def test_entered_is_three_state_and_never_guesses(client, seeded_db_empty_cards):
    """`null` is not `true`. AAON has no prior row, so whether it just entered is
    UNKNOWN — badging it NEW would badge the universe widening as a price move,
    which is exactly what happened in prod on 2026-08-17 (29 of 98 names had no
    prior row because the panel went 256 -> 414 names three days earlier)."""
    _seed(seeded_db_empty_cards)
    entered = {
        c["ticker"]: c["entered"]
        for c in client.get("/api/scanner/value").json()["candidates"]
    }
    assert entered == {"BAX": True, "CL": True, "BRO": False, "AAON": None}


def test_a_name_enters_its_zone_while_its_percentile_does_not_move(
    client, seeded_db_empty_cards
):
    """Non-vacuity for the design choice: BAX reads 0.80 on both dates because
    the percentile is quantised to 1/20, yet it crossed its buy_below. A surface
    keyed on the percentile would have shown nothing happening."""
    _seed(seeded_db_empty_cards)
    bax = next(
        c
        for c in client.get("/api/scanner/value").json()["candidates"]
        if c["ticker"] == "BAX"
    )
    assert bax["entered"] is True
    assert float(bax["spot_percentile"]) == 0.80
    assert float(bax["spot"]) <= float(bax["buy_below"])


def test_no_active_method_version_is_503_not_an_empty_list(
    client, seeded_db_empty_cards
):
    """An empty list asserts 'no name is cheap today'. A dead fundamentals stack
    asserts nothing at all, and the two must not read the same on screen."""
    assert client.get("/api/scanner/value").status_code == 503


def _anchor_row(ticker: str, *, method: str | None, buy_below: float | None) -> dict:
    """Minimum row the table accepts, with the two fields under test explicit."""
    return {
        "ticker": ticker,
        "as_of": D17,
        "engine_version": ENGINE,
        "inputs_hash": f"{ticker}-methodless",
        "company_type": "financials",
        "method": method,
        "buy_below": buy_below,
        "observe_low": None,
        "observe_mid": None,
        "observe_high": None,
        "risk_above": None,
        "spot": 100.0,
        "spot_percentile": None,
        "history_quarters": 20,
        "confidence": "none",
        "confidence_reasons_jsonb": ["test"],
        "inputs_jsonb": {},
        "source_obs_ids": [],
    }


def test_a_methodless_refusal_is_writable(seeded_db_empty_cards):
    """The shape this feature exists to write: `financials` refuses because no
    method applies, so `method` is NULL and every level is absent.

    Paired with the test below deliberately. A constraint that rejected the
    priced case by rejecting ALL methodless rows would pass that test while
    breaking the only reason `method` was made nullable.
    """
    _seed(seeded_db_empty_cards)
    repo = FundamentalAnchorsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    assert repo.insert_anchors([_anchor_row("JPM", method=None, buy_below=None)]) == 1


def test_a_methodless_row_carrying_a_price_is_refused_by_the_database(
    seeded_db_empty_cards,
):
    """The one row shape that would 500 this endpoint for EVERY name in the list.

    `valuation_anchors.method` is nullable (migration 124) so a `financials`
    refusal can decline to name a method; `ValueCandidate.method` is not, because
    every row that reaches it has been filtered on `buy_below IS NOT NULL` and a
    priced row always has a method. Nothing was enforcing the join between those
    two facts. A row with `method` NULL and a real `buy_below` clears the filter,
    reaches a non-nullable field, and fails response validation — so the failure
    is not "one bad row is skipped", it is the whole endpoint returning 500 while
    every other name in it is fine.

    Enforced by `valuation_anchors_methodless_is_refusal` in the schema rather
    than in `build_anchors`, on the same argument migration 118 gives for
    `valuation_anchors_band_ascends`: the builder is one writer among the
    backfills and repairs still to come, and the invariant is a property of the
    table.
    """
    _seed(seeded_db_empty_cards)
    repo = FundamentalAnchorsRepository(
        seeded_db_empty_cards.conn, schema=seeded_db_empty_cards._schema
    )
    with pytest.raises(psycopg.errors.CheckViolation) as exc:
        repo.insert_anchors([_anchor_row("BAC", method=None, buy_below=90.0)])
    # Name the constraint, or this passes on any CHECK the row happens to trip —
    # `valuation_anchors_band_ascends` sits on the same table and a future one
    # will too, and a test that accepts the wrong rejection proves nothing about
    # the shape it was written for.
    assert exc.value.diag.constraint_name == "valuation_anchors_methodless_is_refusal"
    seeded_db_empty_cards.conn.rollback()
