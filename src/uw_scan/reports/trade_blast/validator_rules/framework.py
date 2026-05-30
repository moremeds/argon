"""Framework (v6.0) structural invariants for the additive framework{} block.

Extracted-style rule module matching the other validator_rules helpers: a
single ``_check_*`` function that raises ValueError with a stable,
contract-facing message; the orchestrator in validators.py calls it in
sequence (in BOTH strict and lenient modes — defined-risk is a hard safety
property, like the other v5.1+ checks).

Prose fields are not validated. These checks enforce the assertive-but-honest
contract: conviction is a real count of yes-factors, every candidate is
defined-risk (no naked shorts), and best_setup commits to a real candidate
or an explicit stand_aside. Skips cleanly when ``parsed.framework is None``
(legacy rows / lenient skip / providers that omit the block).
"""

from __future__ import annotations

from uw_scan.models import TradeInsightAiOutcome


def _norm(name: str) -> str:
    return name.strip().lower().replace(" ", "_").replace("-", "_")


def _check_framework_rules(parsed: TradeInsightAiOutcome) -> None:
    """Raise ValueError when the framework{} block violates its invariants."""
    fw = parsed.framework
    if fw is None:
        return  # provider omitted framework (legacy row or lenient skip) — graceful

    # 1. conviction.score == count of factors with status == "yes"
    yes_count = sum(1 for f in fw.conviction.factors if f.status == "yes")
    if fw.conviction.score != yes_count:
        raise ValueError(
            f"conviction.score ({fw.conviction.score}) must equal count of "
            f"yes factors ({yes_count})"
        )
    # 2. header.conviction_n == conviction.score
    if fw.header.conviction_n != fw.conviction.score:
        raise ValueError(
            f"header.conviction_n ({fw.header.conviction_n}) must equal "
            f"conviction.score ({fw.conviction.score})"
        )
    # 3. every candidate is defined-risk (no naked shorts — HARD safety)
    for cand in fw.candidates:
        if not cand.defined_risk:
            raise ValueError(
                f"framework candidate {cand.name!r} is not defined_risk "
                "(no naked shorts allowed)"
            )
    # 4. best_setup.structure resolves to a candidate name OR "stand_aside"
    bs = _norm(fw.best_setup.structure)
    if bs != "stand_aside":
        cand_names = {_norm(c.name): c for c in fw.candidates}
        match = cand_names.get(bs)
        if match is None:
            raise ValueError(
                f"best_setup.structure {fw.best_setup.structure!r} is neither "
                "'stand_aside' nor any candidates[].name"
            )
        if not match.defined_risk:
            raise ValueError(
                f"best_setup picked non-defined-risk candidate {match.name!r}"
            )
    # 5. stand_aside precedence: catalyst.handling==stand_aside => best_setup==stand_aside
    if fw.catalyst.handling == "stand_aside" and bs != "stand_aside":
        raise ValueError(
            "catalyst.handling=stand_aside requires best_setup.structure=stand_aside"
        )
    # 5b. position_type stand_aside <=> best_setup stand_aside (overall stance agrees)
    if (fw.header.position_type == "stand_aside") != (bs == "stand_aside"):
        raise ValueError(
            "header.position_type and best_setup.structure must agree on "
            f"stand_aside (position_type={fw.header.position_type!r}, "
            f"best_setup={fw.best_setup.structure!r})"
        )
    # 6. asymmetry.rule_on <=> conviction.score >= 4 (BOTH directions enforced).
    #    The "indeterminate / <4 non-na factors" case is SUBSUMED: yes ⊆ non-na, so
    #    non_na_count < 4 => score < 4 => rule_on must be False. No separate check
    #    needed; the "insufficient data" distinction lives in conviction.prose, not here.
    if fw.three_axis.asymmetry.rule_on != (fw.conviction.score >= 4):
        raise ValueError(
            "asymmetry.rule_on must equal (conviction.score >= 4) "
            f"(rule_on={fw.three_axis.asymmetry.rule_on}, "
            f"score={fw.conviction.score})"
        )
