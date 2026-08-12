"""Assembly of the reduced §7 fundamental card.

The load-bearing property is suppression fan-out: a violation names a RAW provider
field, the card shows DERIVED features, and exactly the features that consume that
field must go dark. Suppressing too few renders a figure we do not believe;
suppressing too many hides good data behind one bad input.

Figures are NVDA's real FY2027-Q1 features as computed by the shipped engine.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

import pytest

from uw_scan.fundamentals.card import build_card

# Real NVDA row as `fundamental_scores` stores it: NUMERIC columns arrive as
# Decimal, and the contract is float.
NVDA_ROW = {
    "as_of": date(2026, 8, 14),
    "period_end": date(2026, 4, 30),
    "knowledge_date": date(2026, 5, 21),
    "filing_date_known": True,
    "composite": Decimal("1.2043"),
    "rev_growth": Decimal("0.6215"),
    "gross_margin": Decimal("0.7493"),
    "op_margin": Decimal("0.6559"),
    "fcf_margin": Decimal("0.4708"),
    "roe": Decimal("0.9124"),
    "neg_net_debt_ebitda": Decimal("0.3311"),
    "asset_turnover": Decimal("0.9852"),
    "features_present": 7,
    "inputs_hash": "9f2c1b40",
    "source_obs_ids": [101, 102, 103],
}


def _card(row=None, violated=None):
    return build_card(
        ticker="NVDA",
        row=row or dict(NVDA_ROW),
        violated=violated or {},
        engine_version="fundamentals-v1:1a2b3c4d",
    )


def _by_feature(card):
    return {s["feature"]: s for s in card["subscores"]}


def test_clean_row_renders_all_seven():
    card = _card()
    subs = _by_feature(card)
    assert len(subs) == 7
    assert subs["gross_margin"]["value"] == pytest.approx(0.7493)
    assert isinstance(subs["gross_margin"]["value"], float)
    assert card["composite"] == pytest.approx(1.2043)
    assert card["coverage"]["missing"] == []
    assert card["coverage"]["suppressed"] == []


def test_gross_profit_violation_suppresses_only_margin_features_using_it():
    """CEG's real failure. `gross_margin` consumes gross_profit; `op_margin` does
    not, and must survive — a card that blanks the whole income statement over one
    bad field is as wrong as one that renders it."""
    card = _card(
        violated={"gross_profit": ["gross_profit_equals_revenue_despite_costs"]}
    )
    subs = _by_feature(card)

    assert subs["gross_margin"]["value"] is None
    assert subs["gross_margin"]["suppressed_by"] == [
        "gross_profit_equals_revenue_despite_costs"
    ]
    assert subs["op_margin"]["value"] == pytest.approx(0.6559)
    assert subs["op_margin"]["suppressed_by"] == []
    assert card["coverage"]["suppressed"] == ["gross_margin"]


def test_a_shared_input_fans_out_to_every_feature_that_consumes_it():
    """total_revenue feeds five of the seven. The fan-out is the reason the input
    map exists at all."""
    card = _card(violated={"total_revenue": ["synthetic_check"]})
    assert set(card["coverage"]["suppressed"]) == {
        "rev_growth",
        "gross_margin",
        "op_margin",
        "fcf_margin",
        "asset_turnover",
    }
    assert _by_feature(card)["roe"]["value"] == pytest.approx(0.9124)


def test_missing_and_suppressed_are_reported_separately():
    """'never reported' and 'reported and not believed' are different facts."""
    row = dict(NVDA_ROW, roe=None, features_present=6)
    card = _card(row=row, violated={"gross_profit": ["check_a"]})
    assert card["coverage"]["missing"] == ["roe"]
    assert card["coverage"]["suppressed"] == ["gross_margin"]


def test_suppressed_feature_is_not_also_counted_missing():
    """It has a value; we are declining to show it. Counting it as missing would
    overstate what the provider failed to deliver."""
    card = _card(violated={"gross_profit": ["check_a"]})
    assert "gross_margin" not in card["coverage"]["missing"]


def test_features_present_comes_from_the_persisted_column():
    """What the composite was actually scored on. Recomputing it here would drift
    the moment suppression changes, and silently reinterpret every stored score."""
    card = _card(row=dict(NVDA_ROW, features_present=5))
    assert card["coverage"]["features_present"] == 5
    assert card["coverage"]["features_total"] == 7


def test_three_features_claim_no_direction():
    """gross_margin and op_margin measured INVERTED, roe is named by no rubric row.
    A card may not imply a direction for them."""
    subs = _by_feature(_card())
    assert subs["gross_margin"]["direction"] is None
    assert subs["op_margin"]["direction"] is None
    assert subs["roe"]["direction"] is None
    assert subs["rev_growth"]["direction"] == "higher_better"
    assert subs["neg_net_debt_ebitda"]["direction"] == "higher_better"


def test_leverage_and_turnover_are_multiples_not_percentages():
    subs = _by_feature(_card())
    assert subs["neg_net_debt_ebitda"]["unit"] == "turns"
    assert subs["asset_turnover"]["unit"] == "turns"
    assert subs["fcf_margin"]["unit"] == "ratio"


def test_provenance_carries_knowledge_date_and_fallback_flag():
    """The card dates itself by knowledge_date, not the as_of bucket — 28 stored
    rows carry a future as_of purely from the 45-day filing fallback."""
    card = _card(row=dict(NVDA_ROW, filing_date_known=False))
    prov = card["provenance"]
    assert prov["knowledge_date"] == date(2026, 5, 21)
    assert prov["as_of"] == date(2026, 8, 14)
    assert prov["filing_date_known"] is False
    assert prov["source_obs_count"] == 3
    assert prov["engine_version"] == "fundamentals-v1:1a2b3c4d"


def test_null_composite_survives():
    """Fewer than four features present means no composite. The card still renders
    the subscores it has."""
    card = _card(row=dict(NVDA_ROW, composite=None))
    assert card["composite"] is None


def test_missing_source_obs_ids_does_not_crash():
    row = dict(NVDA_ROW)
    del row["source_obs_ids"]
    assert _card(row=row)["provenance"]["source_obs_count"] == 0


def test_multiple_checks_on_one_field_are_deduped_and_ordered():
    card = _card(
        violated={"total_revenue": ["check_b", "check_a"], "gross_profit": ["check_a"]}
    )
    assert _by_feature(card)["gross_margin"]["suppressed_by"] == ["check_a", "check_b"]
