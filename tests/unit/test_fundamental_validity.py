"""Validity policy: which recorded violations reach the math, and how far.

The TTM propagation tests are the ones that matter. A violated `total_revenue`
in one quarter contaminates every trailing window that contains it, and an
implementation that excludes only the violated quarter's own row leaves most of
the damage in place while its counters report the field handled.
"""

from __future__ import annotations

import pytest

from uw_scan.fundamentals.validity import (
    ALL_FEATURE_INPUTS,
    VALIDITY_POLICY_EXCLUDE,
    VALIDITY_POLICY_OFF,
    ViolationEffect,
    apply_validity,
    contaminated,
    effect_for,
    excluded_fields,
    features_touching,
    policy_for_engine,
)


def test_every_shipped_check_declares_an_effect():
    """A check with no declared effect is a check that silently does nothing."""
    from uw_scan.fundamentals.statements import check_violations

    payloads = {
        "income": {
            "total_revenue": "100",
            "gross_profit": "100",
            "cost_of_revenue": "60",
        },
        "balance": {
            "total_assets": "50",
            "total_liabilities": "-10",
            "total_shareholder_equity": "100",
            "common_stock_shares_outstanding": "1",
        },
    }
    seen = {
        v.check_name
        for stmt, payload in payloads.items()
        for v in check_violations(stmt, payload)
    }
    assert seen, "fixture produced no violations; the guard would be vacuous"
    for name in seen:
        assert isinstance(effect_for(name), ViolationEffect)


def test_an_unregistered_check_raises_rather_than_defaulting():
    with pytest.raises(KeyError, match="no declared ViolationEffect"):
        effect_for("some_check_added_next_year")


def test_exclude_field_touches_only_its_own_dependents():
    fields = excluded_fields({"gross_profit": ["gross_profit_equals_revenue_despite_costs"]})
    assert fields == {"gross_profit"}
    assert features_touching(fields) == {"gross_margin"}


def test_exclude_observation_widens_to_the_whole_statement():
    """A self-contradicting balance sheet makes no single line defensible."""
    fields = excluded_fields({"total_assets": ["accounting_identity_reversed"]})
    assert ALL_FEATURE_INPUTS <= fields
    # every feature, because no field on the observation survives
    assert features_touching(fields) == set(
        features_touching(set(ALL_FEATURE_INPUTS))
    )


def test_a_ttm_feature_is_withheld_for_the_whole_window():
    periods = [f"2020-{m:02d}-30" for m in (3, 6, 9, 12)] + [
        f"2021-{m:02d}-30" for m in (3, 6, 9, 12)
    ]
    out = contaminated(periods, {periods[1]: {"total_revenue"}})
    # asset_turnover reads rev_ttm (4 quarters): periods 1..4 are contaminated.
    assert "asset_turnover" in out[periods[1]]
    assert "asset_turnover" in out[periods[4]]
    assert "asset_turnover" not in out[periods[5]]
    # and never backwards — period 0's window closed before the bad quarter.
    assert "asset_turnover" not in out[periods[0]]


def test_rev_growth_reaches_eight_quarters_not_four():
    """It compares TTM at i against TTM at i-4, so its reach is twice as long."""
    periods = [f"20{y}-{m:02d}-30" for y in (20, 21, 22) for m in (3, 6, 9, 12)]
    out = contaminated(periods, {periods[0]: {"total_revenue"}})
    assert "rev_growth" in out[periods[7]]
    assert "rev_growth" not in out[periods[8]]


def test_a_quarterly_ratio_does_not_propagate():
    periods = ["2020-03-30", "2020-06-30", "2020-09-30"]
    out = contaminated(periods, {periods[0]: {"gross_profit"}})
    assert out[periods[0]] == {"gross_margin"}
    assert out[periods[1]] == set()


def test_apply_validity_nulls_values_and_counts_them():
    feats = {
        "AAPL": {
            "2020-03-30": {"gross_margin": 1.0, "op_margin": 0.3},
            "2020-06-30": {"gross_margin": 0.4, "op_margin": 0.3},
        }
    }
    out, counters = apply_validity(feats, {"AAPL": {"2020-03-30": {"gross_profit"}}})
    assert out["AAPL"]["2020-03-30"]["gross_margin"] is None
    assert out["AAPL"]["2020-03-30"]["op_margin"] == 0.3
    assert out["AAPL"]["2020-06-30"]["gross_margin"] == 0.4
    assert counters == {"values_excluded": 1, "periods_touched": 1}


def test_an_already_null_value_is_not_counted_as_an_exclusion():
    feats = {"AAPL": {"2020-03-30": {"gross_margin": None}}}
    _, counters = apply_validity(feats, {"AAPL": {"2020-03-30": {"gross_profit"}}})
    assert counters["values_excluded"] == 0


def test_no_violations_is_a_passthrough():
    feats = {"AAPL": {"2020-03-30": {"gross_margin": 0.4}}}
    out, counters = apply_validity(feats, {})
    assert out == feats
    assert counters == {"values_excluded": 0, "periods_touched": 0}


def test_the_policy_comes_from_the_engine_version():
    assert policy_for_engine("fundamentals-v1:77aea364") == VALIDITY_POLICY_OFF
    assert policy_for_engine("fundamentals-v2:77aea364") == VALIDITY_POLICY_EXCLUDE


def test_an_undeclared_engine_refuses_rather_than_inheriting_v1():
    with pytest.raises(KeyError, match="no declared validity policy"):
        policy_for_engine("fundamentals-v3:deadbeef")
