"""Dimensions and the permission ladder (spec §6.4).

The authority assignments are the point. Two dimensions are deliberately capped
at `descriptive` and both caps are load-bearing:

- `operating_quality`'s inputs measured INVERTED (high-margin names
  underperformed in the 2026-08-12 validation), so no direction may be claimed;
- `valuation`'s own-history finding was computed by a script that paired raw
  closes with shares restated to today's split basis, and was never rerun.

A test that only checked the arithmetic would pass while the aggregate quietly
carried a contradicted sign.
"""

from __future__ import annotations

from uw_scan.fundamentals.dimensions import (
    AGGREGATE_DIMENSIONS,
    DIMENSION_AUTHORITY,
    DIMENSIONS,
    PROGRAM_CEILING,
    Authority,
    dimension_values,
    evidence_quality,
    max_authority,
    priority_aggregate,
)

FULL_Z = {
    "rev_growth": 1.0,
    "gross_margin": 2.0,
    "op_margin": 0.0,
    "fcf_margin": -1.0,
    "roe": 0.5,
    "neg_net_debt_ebitda": 0.25,
    "asset_turnover": 1.5,
}


def test_no_dimension_may_claim_investment_ranking():
    """It needs the GX gate this program does not provide."""
    assert Authority.INVESTMENT_RANKING not in DIMENSION_AUTHORITY.values()
    assert PROGRAM_CEILING is Authority.RESEARCH_PRIORITY


def test_the_contradicted_dimension_is_capped_at_descriptive():
    assert DIMENSION_AUTHORITY["operating_quality"] is Authority.DESCRIPTIVE


def test_valuation_carries_a_within_name_direction_only():
    """Raised to directional_monitor 2026-08-25 by the split-basis rerun.

    A stronger authority is not a wider one: it still may not enter the
    cross-name aggregate, because cross-sectionally value measured INVERTED.
    """
    assert DIMENSION_AUTHORITY["valuation"] is Authority.DIRECTIONAL_MONITOR
    assert "valuation" not in AGGREGATE_DIMENSIONS


def test_only_research_priority_dimensions_enter_the_aggregate():
    """Excluded in BOTH directions — weaker signs and wider-than-licensed ones."""
    assert "operating_quality" not in AGGREGATE_DIMENSIONS
    assert "valuation" not in AGGREGATE_DIMENSIONS
    for dim in AGGREGATE_DIMENSIONS:
        assert DIMENSION_AUTHORITY[dim] is Authority.RESEARCH_PRIORITY


def test_every_dimension_declares_an_authority():
    assert set(DIMENSION_AUTHORITY) == set(DIMENSIONS)


def test_a_dimension_averages_its_features():
    out = dimension_values(FULL_Z)
    assert out["capital_efficiency"]["value"] == (0.5 + 1.5) / 2
    assert out["capital_efficiency"]["present"] == 2
    assert out["growth"]["value"] == 1.0


def test_a_missing_input_yields_none_not_zero():
    """Zero is the cross-section MEAN — writing it fabricates an observation."""
    out = dimension_values({**FULL_Z, "neg_net_debt_ebitda": None})
    assert out["balance_sheet"]["value"] is None
    assert out["balance_sheet"]["present"] == 0
    assert out["balance_sheet"]["expected"] == 1


def test_a_partially_present_dimension_averages_what_is_there():
    out = dimension_values({**FULL_Z, "roe": None})
    assert out["capital_efficiency"]["value"] == 1.5
    assert out["capital_efficiency"]["present"] == 1
    assert out["capital_efficiency"]["expected"] == 2


def test_the_aggregate_renormalizes_over_present_dimensions_and_says_which():
    dims = dimension_values({**FULL_Z, "neg_net_debt_ebitda": None})
    agg = priority_aggregate(dims)
    assert "balance_sheet" in agg["missing"]
    assert "balance_sheet" not in agg["used"]
    # renormalized over the three that were present, NOT diluted by a zero
    expected = (1.0 + (-1.0) + 1.0) / 3
    assert abs(agg["value"] - expected) < 1e-12


def test_the_aggregate_refuses_rather_than_calling_one_dimension_a_priority():
    thin = {"growth": {"value": 1.0}, "balance_sheet": {"value": None},
            "cash_conversion": {"value": None}, "capital_efficiency": {"value": None}}
    agg = priority_aggregate(thin)
    assert agg["value"] is None
    assert agg["authority"] == Authority.DESCRIPTIVE.value
    assert "1 of 4" in agg["refusal"]


def test_the_aggregate_never_exceeds_the_program_ceiling():
    agg = priority_aggregate(dimension_values(FULL_Z))
    assert agg["authority"] == PROGRAM_CEILING.value


def test_evidence_quality_measures_what_argon_knows_not_the_business():
    out = evidence_quality(true_pit=3, total=4, excluded_values=1)
    assert out["value"] == 0.75
    assert out["authority"] == Authority.DESCRIPTIVE.value
    assert out["excluded_values"] == 1


def test_evidence_quality_with_no_observations_is_none_not_zero():
    out = evidence_quality(true_pit=0, total=0, excluded_values=0)
    assert out["value"] is None


def test_max_authority_is_capped_at_the_ceiling():
    assert max_authority([]) is Authority.DESCRIPTIVE
    assert max_authority(["descriptive", "research_priority"]) is (
        Authority.RESEARCH_PRIORITY
    )
    # even asked for something stronger, it refuses to hand it back
    assert max_authority(["investment_ranking"]) is PROGRAM_CEILING
