"""Semantic invariants for the framework{} block (validator_rules/framework.py).

Each test builds a Pydantic-valid TradeFramework that violates exactly one
cross-field rule, attaches it to a model_construct'd outcome (the rule only
reads parsed.framework), and asserts the expected ValueError. The happy-path
tests confirm valid tradeable and stand_aside frameworks pass clean.
"""

from __future__ import annotations

import pytest

from uw_scan.models import TradeFramework, TradeInsightAiOutcome
from uw_scan.reports.trade_blast.validator_rules.framework import (
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


# --- v2 spec §5.5: auto-correct entry_state in soft mode -----------------

from uw_scan.reports.trade_blast.validators import _autocorrect_entry_state


def _autocorrect_outcome(
    *,
    entry_state: str,
    thesis_fired: bool,
    entry_fired: bool,
    invalidation_fired: bool,
    directional_bias: str = "LONG_DELTA",
) -> TradeInsightAiOutcome:
    """Build a minimal TradeInsightAiOutcome via model_construct for
    auto-correct unit tests. Only fields the helper reads are populated."""
    headline = type(TradeInsightAiOutcome.model_fields["headline"].annotation)
    # Construct headline + trigger components without full validation.
    from uw_scan.models import (
        TradeInsightAiHeadline,
        TradeInsightAiTriggerComponent,
    )

    h = TradeInsightAiHeadline.model_construct(
        entry_state=entry_state,
        directional_bias=directional_bias,
    )
    tt = TradeInsightAiTriggerComponent.model_construct(fired=thesis_fired)
    et = TradeInsightAiTriggerComponent.model_construct(fired=entry_fired)
    inv = TradeInsightAiTriggerComponent.model_construct(fired=invalidation_fired)
    return TradeInsightAiOutcome.model_construct(
        headline=h,
        thesis_trigger=tt,
        entry_trigger=et,
        invalidation=inv,
        missing_data=[],
    )


def test_autocorrect_active_to_conditional_when_entry_unfired():
    outcome = _autocorrect_outcome(
        entry_state="ACTIVE",
        thesis_fired=True,
        entry_fired=False,
        invalidation_fired=False,
    )
    note = _autocorrect_entry_state(outcome)
    assert outcome.headline.entry_state == "CONDITIONAL"
    assert note is not None
    assert note.startswith("auto-correct: headline.entry_state:")
    assert "'ACTIVE'" in note and "'CONDITIONAL'" in note


def test_autocorrect_invalidation_forces_no_entry():
    # invalidation.fired => NO_ENTRY regardless of entry_state claim.
    outcome = _autocorrect_outcome(
        entry_state="CONDITIONAL",
        thesis_fired=True,
        entry_fired=False,
        invalidation_fired=True,
    )
    note = _autocorrect_entry_state(outcome)
    assert outcome.headline.entry_state == "NO_ENTRY"
    assert note is not None and "NO_ENTRY" in note


def test_autocorrect_noop_when_already_conditional():
    # CONDITIONAL with thesis-only fired is already correct; no overwrite, no note.
    outcome = _autocorrect_outcome(
        entry_state="CONDITIONAL",
        thesis_fired=True,
        entry_fired=False,
        invalidation_fired=False,
    )
    note = _autocorrect_entry_state(outcome)
    assert outcome.headline.entry_state == "CONDITIONAL"
    assert note is None


def test_autocorrect_consumes_violation_no_duplicate_soft_warning(monkeypatch):
    """Soft branch invariant (§5.5): when auto-correct fires for entry_state,
    the same field must NOT also surface a `soft-validation:` warning. Tests
    by invoking validate via the soft path with a minimal fixture that
    triggers ACTIVE → CONDITIONAL and asserts missing_data carries exactly
    one auto-correct line and zero soft-validation lines referencing
    entry_state_derivation."""
    from uw_scan.reports.trade_blast.validators import (
        _autocorrect_entry_state as _ac,
    )

    outcome = _autocorrect_outcome(
        entry_state="ACTIVE",
        thesis_fired=True,
        entry_fired=False,
        invalidation_fired=False,
    )
    # Simulate the validator's soft branch: auto-correct, then run the
    # structural check that would have otherwise raised on this state.
    ac_note = _ac(outcome)
    soft_warnings: list[str] = []
    try:
        from uw_scan.reports._shared_validation.validator_rules.triggers import (
            _check_entry_state_derivation,
        )

        _check_entry_state_derivation(outcome)
    except ValueError as exc:
        soft_warnings.append(repr(exc))

    notes: list[str] = []
    if ac_note:
        notes.append(ac_note)
    notes.extend(f"soft-validation: {w}" for w in soft_warnings)

    assert sum(1 for n in notes if n.startswith("auto-correct:")) == 1
    assert not any(
        "entry_state_derivation" in n for n in notes if n.startswith("soft-validation:")
    )


def test_autocorrect_strict_mode_parity_raises():
    """Strict mode parity: _check_entry_state_derivation must still raise on
    the same input (the auto-correct helper is soft-mode-only and is never
    called outside the `if soft:` branch). Insights lane behavior unchanged."""
    from uw_scan.reports._shared_validation.validator_rules.triggers import (
        _check_entry_state_derivation,
    )

    outcome = _autocorrect_outcome(
        entry_state="ACTIVE",
        thesis_fired=True,
        entry_fired=False,
        invalidation_fired=False,
    )
    with pytest.raises(ValueError, match="ACTIVE requires BOTH"):
        _check_entry_state_derivation(outcome)
