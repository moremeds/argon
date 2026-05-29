"""Semantic invariants for the framework{} block (validator_rules/framework.py).

Each test builds a Pydantic-valid TradeFramework that violates exactly one
cross-field rule, attaches it to a model_construct'd outcome (the rule only
reads parsed.framework), and asserts the expected ValueError. The happy-path
tests confirm valid tradeable and stand_aside frameworks pass clean.
"""

from __future__ import annotations

import pytest

from uw_scan.models import TradeFramework, TradeInsightAiOutcome
from uw_scan.reports.trade_insights_ai.validator_rules.framework import (
    _check_framework_rules,
)


def _factors(yes: int, total: int = 8) -> list[dict]:
    out = [{"name": f"f{i}", "status": "yes"} for i in range(yes)]
    out += [{"name": f"f{i}", "status": "na"} for i in range(yes, total)]
    return out


def build_framework(
    *,
    position_type: str = "swing",
    conviction_n: int = 4,
    score: int = 4,
    yes_factors: int = 4,
    rule_on: bool = True,
    structure_family: str = "directional_defined_risk",
    handling: str = "exit_before_print",
    best_setup: str = "bull put spread",
    candidates=(("bull put spread", True),),
) -> dict:
    cand_list = [
        {"name": name, "legs": ["long X put", "short Y put"], "defined_risk": dr}
        for name, dr in candidates
    ]
    return {
        "header": {
            "thesis_one_liner": "x",
            "position_type": position_type,
            "spot": "100",
            "conviction_n": conviction_n,
        },
        "three_axis": {
            "direction": {"verdict": "bull", "prose": "p"},
            "vega": {"regime": "low_iv", "prose": "p"},
            "asymmetry": {
                "rule_on": rule_on,
                "structure_family": structure_family,
                "prose": "p",
            },
        },
        "gamma": {"regime": "long", "prose": "p"},
        "catalyst": {"handling": handling, "prose": "p"},
        "conviction": {"score": score, "prose": "p", "factors": _factors(yes_factors)},
        "confluence": {"aligned": True, "signals": [], "prose": "p"},
        "pitfalls": [],
        "candidates": cand_list,
        "best_setup": {
            "structure": best_setup,
            "legs": [],
            "cost": None,
            "max_risk": None,
            "rationale": "r",
            "why_not_alternatives": "",
            "invalidation": "inv",
        },
        "what_changes": [],
        "bottom_line": "bl",
    }


def _run(fw_dict: dict) -> None:
    fw = TradeFramework.model_validate(fw_dict)
    outcome = TradeInsightAiOutcome.model_construct(framework=fw)
    _check_framework_rules(outcome)


def test_none_framework_is_noop():
    outcome = TradeInsightAiOutcome.model_construct(framework=None)
    _check_framework_rules(outcome)  # no raise


def test_valid_tradeable_framework_passes():
    _run(build_framework())


def test_valid_stand_aside_passes():
    _run(
        build_framework(
            position_type="stand_aside",
            best_setup="stand_aside",
            handling="stand_aside",
            candidates=(),
            score=0,
            yes_factors=0,
            conviction_n=0,
            rule_on=False,
            structure_family="pin_vega",
        )
    )


def test_naked_candidate_rejected():
    with pytest.raises(ValueError, match="defined_risk"):
        _run(build_framework(candidates=(("bull put spread", False),)))


def test_best_setup_must_match_candidate_or_stand_aside():
    with pytest.raises(ValueError, match="best_setup.structure"):
        _run(build_framework(best_setup="ghost structure"))


def test_conviction_count_mismatch_rejected():
    with pytest.raises(ValueError, match="conviction.score"):
        _run(build_framework(score=4, yes_factors=2, conviction_n=4))


def test_conviction_n_must_equal_score():
    with pytest.raises(ValueError, match="conviction_n"):
        _run(build_framework(conviction_n=3, score=4, yes_factors=4))


def test_stand_aside_precedence():
    with pytest.raises(ValueError, match="stand_aside"):
        _run(build_framework(handling="stand_aside", best_setup="bull put spread"))


def test_asymmetry_rule_on_requires_score_ge_4():
    with pytest.raises(ValueError, match="asymmetry"):
        _run(build_framework(rule_on=True, score=3, yes_factors=3, conviction_n=3))


def test_asymmetry_rule_off_rejected_when_score_ge_4():
    with pytest.raises(ValueError, match="asymmetry"):
        _run(build_framework(rule_on=False, score=4, yes_factors=4))


def test_position_type_stand_aside_requires_best_setup_stand_aside():
    with pytest.raises(ValueError, match="stand_aside"):
        _run(build_framework(position_type="stand_aside", best_setup="bull put spread"))
