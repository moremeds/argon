"""Deterministic validators for the trade_blast lane.

`validate_trade_insights_ai_outcome` delegates to the shared
trade_insights_ai validator with the blast lane's deltas wired in: the
trade-blast prompt version, the extra volatile hash keys, the v6.0
framework structural check, soft-mode structural-check downgrading, and
the entry-state autocorrector. `_autocorrect_entry_state` stays
blast-owned — it is the soft-mode mechanical entry_state repair.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from uw_scan.models import TradeInsightAiOutcome
from uw_scan.reports._shared_validation.util import _iso_z  # noqa: F401
from uw_scan.reports._shared_validation.validator_rules.identity import (  # noqa: F401
    _candidate_map,
    _known_idea_id,
)
from uw_scan.reports._shared_validation.validator_rules.imperative import (  # noqa: F401
    _reject_imperative_text,
)
from uw_scan.reports._shared_validation.validator_rules.sources import (  # noqa: F401
    _drop_invalid_source_path_in_lenient,
    _validate_source_path_item,
)
from uw_scan.reports._shared_validation.validator_rules.structure import (  # noqa: F401
    _check_conditional_quote_validity,
    _check_delta_match,
    _check_dte_band_consistency,
    _check_mode_structure_consistency,
    _check_trigger_strike_consistency,
)
from uw_scan.reports._shared_validation.validator_rules.triggers import (  # noqa: F401
    _check_active_trigger_evidence,
    _check_anti_pin_cap_scope,
    _check_entry_state_derivation,
    _check_headline_title_length,
    _check_legs_align_with_triggers,
    _check_legs_match_strategy,
    _check_min_rr_for_conditional_c,
    _check_thesis_archetype_consistency,
)
from uw_scan.reports.trade_insights_ai.validators import (
    validate_trade_insights_ai_outcome as _base_validate_outcome,
)

from .analysis_input import (  # noqa: F401
    _EXTRA_VOLATILE_HASH_KEYS,
    hash_trade_insights_ai_analysis_input,
)
from .prompt_text import (  # noqa: F401
    FINAL_RATING_VALUES,
    PREFERRED_STRATEGY_FAMILY_IDS,
    PROMPT_VERSION,
    STRATEGY_FAMILY_IDS,
)
from .validator_rules.framework import _check_framework_rules  # noqa: F401


def _autocorrect_entry_state(parsed: TradeInsightAiOutcome) -> str | None:
    """Soft-mode-only: mechanically correct headline.entry_state when the
    truth table is unambiguous. Returns a transparency note when an
    overwrite happened, else None.

    Scope (mechanical only — matches v5.3 ENTRY_STATE derivation):
      - invalidation.fired               => NO_ENTRY
      - ACTIVE without (thesis AND entry).fired => CONDITIONAL

    The CONDITIONAL/NO_ENTRY split when no triggers have fired is left to
    the model (see triggers.py:422-425 — legitimate judgment between
    data-quality and opportunity-quality).
    """
    state = parsed.headline.entry_state
    if parsed.headline.directional_bias == "WAIT":
        return None  # WAIT path enforced by mode-structure consistency
    thesis_fired = parsed.thesis_trigger.fired
    entry_fired = parsed.entry_trigger.fired
    invalidation_fired = parsed.invalidation.fired

    derived: str | None = None
    if invalidation_fired:
        derived = "NO_ENTRY"
    elif state == "ACTIVE" and not (thesis_fired and entry_fired):
        derived = "CONDITIONAL"

    if derived is None or derived == state:
        return None
    parsed.headline.entry_state = derived  # type: ignore[assignment]
    return (
        f"auto-correct: headline.entry_state: {state!r} -> {derived!r} "
        f"(thesis_fired={thesis_fired}, entry_fired={entry_fired}, "
        f"invalidation_fired={invalidation_fired}). v5.3 ENTRY_STATE is "
        "mechanical when the truth table is unambiguous."
    )


def validate_trade_insights_ai_outcome(
    outcome: dict[str, Any] | TradeInsightAiOutcome,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    lenient: bool = False,
    soft: bool = False,
) -> TradeInsightAiOutcome:
    """Validate model output against immutable deterministic inputs —
    shared pipeline with the blast lane's `soft` framework mode wired in.

    `soft=True` downgrades the v5.3 structural consistency checks to
    collected warnings (appended to ``missing_data`` as
    ``soft-validation: ...``) so real framework output always renders.
    The no-naked-shorts safety property stays HARD even in soft mode:
    any framework candidate that is not ``defined_risk`` still raises.
    """

    # Function-local import: the lenient module depends on this package's
    # constants, so a module-level import here would deadlock at first-load.
    # Deferring keeps the dependency edge runtime-only and matches the
    # pre-refactor behavior (which late-imported the same symbol here).
    from uw_scan.reports.trade_blast._lenient import _coerce_claude_outcome_dict

    return _base_validate_outcome(
        outcome,
        deterministic_payload,
        produced_at=produced_at,
        lenient=lenient,
        soft=soft,
        prompt_version=PROMPT_VERSION,
        extra_volatile_keys=_EXTRA_VOLATILE_HASH_KEYS,
        extra_structural_checks=[_check_framework_rules],
        soft_autocorrect=_autocorrect_entry_state,
        lenient_coercer=_coerce_claude_outcome_dict,
    )
