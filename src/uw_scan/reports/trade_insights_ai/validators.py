"""Deterministic HARD validators for Trade Insights AI outcomes.

Every rule raises `ValueError` when model output violates the contract the
prompt promises. `validate_trade_insights_ai_outcome` is the public entry point.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from uw_scan.models import TradeInsightAiOutcome

from .analysis_input import (
    _iso_z,
    hash_trade_insights_ai_analysis_input,
)
from .prompt_text import (
    FINAL_RATING_VALUES,
    PREFERRED_STRATEGY_FAMILY_IDS,
    PROMPT_VERSION,
    STRATEGY_FAMILY_IDS,
)
from .validator_rules.identity import _candidate_map, _known_idea_id
from .validator_rules.imperative import _reject_imperative_text
from .validator_rules.sources import (
    _drop_invalid_source_path_in_lenient,
    _validate_source_path_item,
)
from .validator_rules.structure import (
    _check_conditional_quote_validity,
    _check_delta_match,
    _check_dte_band_consistency,
    _check_mode_structure_consistency,
    _check_trigger_strike_consistency,
)
from .validator_rules.triggers import (
    _check_active_trigger_evidence,
    _check_anti_pin_cap_scope,
    _check_entry_state_derivation,
    _check_headline_title_length,
    _check_legs_align_with_triggers,
    _check_legs_match_strategy,
    _check_min_rr_for_conditional_c,
    _check_thesis_archetype_consistency,
)


def validate_trade_insights_ai_outcome(
    outcome: dict[str, Any] | TradeInsightAiOutcome,
    deterministic_payload: dict[str, Any],
    *,
    produced_at: datetime,
    lenient: bool = False,
) -> TradeInsightAiOutcome:
    """Validate model output against immutable deterministic inputs.

    `lenient=True` (Claude only — see issue #67) pre-processes the raw dict
    through `_coerce_claude_outcome_dict` to capture partial/off-schema output,
    then RELAXES only the equality checks that require provider-internal
    consistency:

    * unknown idea_ids in best_expressions / rejected_ideas / preferred /
      conflicts are accepted (lenient capture);
    * source_path validation drops invalid paths to None instead of raising.

    Safety / integrity checks STILL RUN in lenient mode:

    * undefined-risk strategy family (e.g. `short_strangle`) rejection —
      enforces the no-naked-shorts project rule even for Claude;
    * strategy-family status_observed/risk_flags equality (the coercer
      synthesizes the canonical values, so this passes automatically);
    * known-candidate status_observed/risk_flags equality (the coercer
      overwrites these from the deterministic candidate so this passes);
    * guardrails all-true (an explicit False from Claude is rejected);
    * imperative-text rejection (safety guardrail on free text).

    NOTE: A pre-validated TradeInsightAiOutcome instance bypasses the
    coercion step. Production callers always pass dicts from the runner.
    """

    # Function-local import: lenient module depends on this package's constants,
    # so a module-level import here would deadlock at first-load. Deferring keeps
    # the dependency edge runtime-only and matches the pre-split single-file
    # behavior (which late-imported the same symbol at the bottom of the module).
    from uw_scan.reports.trade_insights_ai_lenient import _coerce_claude_outcome_dict

    expected_hash = hash_trade_insights_ai_analysis_input(deterministic_payload)
    if lenient and not isinstance(outcome, TradeInsightAiOutcome):
        outcome = _coerce_claude_outcome_dict(
            outcome,
            deterministic_payload,
            produced_at=produced_at,
            expected_analysis_input_hash=expected_hash,
        )

    parsed = (
        outcome
        if isinstance(outcome, TradeInsightAiOutcome)
        else TradeInsightAiOutcome.model_validate(outcome)
    )
    expected_produced_at = _iso_z(produced_at)
    if _iso_z(parsed.analysis_produced_at) != expected_produced_at:
        raise ValueError(
            "analysis_produced_at does not match worker-produced timestamp"
        )
    if parsed.schema_version != PROMPT_VERSION:
        raise ValueError("schema_version does not match prompt version")
    if parsed.headline.conviction not in FINAL_RATING_VALUES:
        raise ValueError("final rating must be one of A, B, C, D, or F")
    if parsed.ticker != deterministic_payload.get("ticker"):
        raise ValueError("ticker does not match deterministic payload")
    if parsed.snapshot.run_id != deterministic_payload.get("run_id"):
        raise ValueError("snapshot.run_id does not match deterministic payload")
    if parsed.snapshot.trade_insights_input_hash != deterministic_payload.get(
        "trade_insights_input_hash"
    ):
        raise ValueError(
            "trade_insights_input_hash does not match deterministic payload"
        )
    if parsed.snapshot.analysis_input_hash != expected_hash:
        raise ValueError("analysis_input_hash does not match deterministic payload")

    candidates = _candidate_map(deterministic_payload)

    # Strict-only: unknown idea_ids in best_expressions / rejected_ideas /
    # preferred_expression / conflicts are rejected outright. The lenient
    # coercer accepts them so Claude's incoherence is captured visibly.
    if not lenient:
        for item in [*parsed.best_expressions, *parsed.rejected_ideas]:
            if not _known_idea_id(item.idea_id, candidates):
                raise ValueError(f"unknown idea_id referenced: {item.idea_id}")
        if parsed.preferred_expression is not None and not _known_idea_id(
            parsed.preferred_expression.idea_id, candidates
        ):
            raise ValueError(
                f"unknown idea_id referenced: {parsed.preferred_expression.idea_id}"
            )
        for conflict in parsed.conflicts:
            for idea_id in conflict.affected_idea_ids:
                if not _known_idea_id(idea_id, candidates):
                    raise ValueError(f"unknown idea_id referenced: {idea_id}")

    # ALWAYS (both strict and lenient): safety checks for strategy-family
    # ids (undefined-risk rejection, status_observed/risk_flags discipline)
    # and known-candidate status/risk_flags equality.
    #
    # v5.3 update (status_observed drift normalization): for known
    # candidate idea_ids we now OVERWRITE status_observed and
    # risk_flags_observed with the deterministic candidate's persisted
    # values BEFORE the equality assertion. This implements the
    # no-whitewashing rule by construction rather than by rejection,
    # eliminating non-deterministic Codex drift (observed 4x across NVDA-G
    # / TSLA-G x2 / NOK-F over a 10-hour window). The lenient coercer
    # already did this for Claude — extending the same overwrite to all
    # providers aligns the contract symmetrically. The equality assertion
    # is retained as a defensive backstop.
    #
    # Exception: the v5.1 pre-trigger escalation case (CONDITIONAL +
    # status_observed='candidate_pre_trigger' on preferred_expression) is
    # preserved — it's a legitimate escalation, not drift.
    echo_items = list(parsed.best_expressions)
    if parsed.preferred_expression is not None:
        echo_items.append(parsed.preferred_expression)
    for item in echo_items:
        if item.idea_id in STRATEGY_FAMILY_IDS:
            if item.idea_id not in PREFERRED_STRATEGY_FAMILY_IDS:
                raise ValueError(
                    f"undefined-risk strategy family cannot be preferred: {item.idea_id}"
                )
            if item.status_observed != "strategy_review":
                raise ValueError(
                    f"strategy status_observed must be strategy_review for {item.idea_id}"
                )
            if item.risk_flags_observed != []:
                raise ValueError(
                    f"strategy risk_flags_observed must be empty for {item.idea_id}"
                )
            continue
        if item.idea_id in candidates:
            candidate = candidates[item.idea_id]
            candidate_status = candidate.get("status")
            candidate_risk_flags = list(candidate.get("risk_flags") or [])
            is_pretrigger_escalation = (
                item is parsed.preferred_expression
                and parsed.headline.entry_state == "CONDITIONAL"
                and item.status_observed == "candidate_pre_trigger"
                and candidate_status == "candidate"
            )
            # v5.3 CONDITIONAL → strategy_review preservation: when the model
            # correctly translates the candidate row's pre-trigger status to
            # "strategy_review" under CONDITIONAL (per the prompt contract),
            # the overwrite below must NOT clobber it back to "candidate" —
            # _check_conditional_quote_validity would immediately reject that
            # exact value. Without this escape, any preferred picking a known
            # candidate id under CONDITIONAL fails reliably (CRWV/MCD codex
            # failures observed 2026-05-26..27).
            is_conditional_strategy_review_translation = (
                item is parsed.preferred_expression
                and parsed.headline.entry_state == "CONDITIONAL"
                and item.status_observed == "strategy_review"
                and candidate_status == "candidate"
            )
            preserve_status = (
                is_pretrigger_escalation or is_conditional_strategy_review_translation
            )
            if not preserve_status and item.status_observed != candidate_status:
                item.status_observed = candidate_status
            if item.risk_flags_observed != candidate_risk_flags:
                item.risk_flags_observed = candidate_risk_flags
            if not preserve_status and item.status_observed != candidate_status:
                raise ValueError(f"status_observed changed for idea_id {item.idea_id}")
            if item.risk_flags_observed != candidate_risk_flags:
                raise ValueError(
                    f"risk_flags_observed changed for idea_id {item.idea_id}"
                )

    # ALWAYS: guardrails truthiness — an explicit False from Claude must
    # not contradict the persisted "succeeded" status.
    if not (
        parsed.guardrails.statuses_preserved
        and parsed.guardrails.risk_flags_preserved
        and parsed.guardrails.no_executable_recommendations
    ):
        raise ValueError("guardrails must all be true")

    # ALWAYS: v5 mode-structure + delta-match consistency. These are the
    # core directional-swing invariants — picking a vol-seller for a
    # directional swing is the failure mode v5 exists to eliminate, so we
    # enforce in BOTH strict and lenient modes. The lenient coercer can
    # attempt to normalize obvious mismatches, but any residual violation
    # must surface as an error rather than be silently captured (mirrors
    # the undefined-risk strategy-family check above).
    _check_mode_structure_consistency(parsed)
    _check_delta_match(parsed)
    # v5.1 additions: trigger/strike consistency, DTE band consistency,
    # conditional quote validity. Enforced in BOTH strict and lenient modes
    # because they encode the core directional-correctness invariants the
    # v5.1 reviewers (chatgpt + claude) flagged as v5 failure modes.
    _check_trigger_strike_consistency(parsed, candidates)
    _check_dte_band_consistency(parsed, candidates)
    _check_conditional_quote_validity(parsed)
    # v5.2 additions: enforced in BOTH strict and lenient modes.
    _check_active_trigger_evidence(parsed)
    _check_anti_pin_cap_scope(parsed)
    _check_thesis_archetype_consistency(parsed)
    _check_headline_title_length(parsed, lenient=lenient)
    _check_min_rr_for_conditional_c(parsed)
    # v5.3 additions: trigger-component state machine. Enforced in BOTH
    # strict and lenient modes because they encode the v5.3 contract's
    # core promise (ENTRY_STATE is mechanical; legs are explicit; the
    # spread is tied to the trigger components).
    _check_legs_match_strategy(parsed)
    _check_legs_align_with_triggers(parsed)
    _check_entry_state_derivation(parsed)

    # Strict: source_path validation raises on invalid prefixes.
    # Lenient: invalid prefixes are dropped to None with a missing_data note.
    if not lenient:
        for card in parsed.metric_cards:
            _validate_source_path_item(card, deterministic_payload, parsed)
        for section in (
            parsed.section_cards.market_structure,
            parsed.section_cards.volatility,
            parsed.section_cards.flow_positioning,
        ):
            for highlight in section.highlights:
                _validate_source_path_item(highlight, deterministic_payload, parsed)
            for level in section.levels:
                _validate_source_path_item(level, deterministic_payload, parsed)
    else:
        missing_data = list(parsed.missing_data)
        for card in parsed.metric_cards:
            _drop_invalid_source_path_in_lenient(
                card, deterministic_payload, parsed, missing_data
            )
        for section in (
            parsed.section_cards.market_structure,
            parsed.section_cards.volatility,
            parsed.section_cards.flow_positioning,
        ):
            for highlight in section.highlights:
                _drop_invalid_source_path_in_lenient(
                    highlight, deterministic_payload, parsed, missing_data
                )
            for level in section.levels:
                _drop_invalid_source_path_in_lenient(
                    level, deterministic_payload, parsed, missing_data
                )
        # Persist any new notes back onto the parsed outcome
        if len(missing_data) != len(parsed.missing_data):
            parsed.missing_data = missing_data

    _reject_imperative_text(parsed)
    return parsed
